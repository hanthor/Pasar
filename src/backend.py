# backend.py - Homebrew backend using the formulae.brew.sh JSON API + local brew CLI
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import os
import subprocess
import threading
from urllib.request import urlopen, Request
from urllib.error import URLError

import gi
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gio, GLib, GObject, GdkPixbuf


# Homebrew API endpoints
FORMULA_API = 'https://formulae.brew.sh/api/formula.json'
CASK_API = 'https://formulae.brew.sh/api/cask.json'
FORMULA_DETAIL_API = 'https://formulae.brew.sh/api/formula/{}.json'
CASK_DETAIL_API = 'https://formulae.brew.sh/api/cask/{}.json'


def _is_flatpak():
    """Detect if running inside a Flatpak sandbox."""
    return os.path.exists('/.flatpak-info')


def _find_brew():
    """Find the brew executable."""
    candidates = [
        '/home/linuxbrew/.linuxbrew/bin/brew',
        '/opt/homebrew/bin/brew',
        '/usr/local/bin/brew',
    ]
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    # fallback: try PATH
    try:
        result = subprocess.run(['which', 'brew'], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return 'brew'


IN_FLATPAK = _is_flatpak()
BREW_BIN = _find_brew()


def _brew_cmd(args):
    """Build a command list for running brew, using flatpak-spawn if sandboxed."""
    if IN_FLATPAK:
        # Use flatpak-spawn to run brew on the host
        return ['flatpak-spawn', '--host', 'bash', '-c',
                f'eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)" && brew {" ".join(args)}']
    else:
        return [BREW_BIN] + args


class Package(GObject.Object):
    """Represents a Homebrew formula or cask."""

    __gtype_name__ = 'PasarPackage'

    name = GObject.Property(type=str, default='')
    full_name = GObject.Property(type=str, default='')
    description = GObject.Property(type=str, default='')
    homepage = GObject.Property(type=str, default='')
    version = GObject.Property(type=str, default='')
    pkg_type = GObject.Property(type=str, default='formula')  # 'formula' or 'cask'
    installed = GObject.Property(type=bool, default=False)
    display_name = GObject.Property(type=str, default='')
    icon_url = GObject.Property(type=str, default='')
    license_ = GObject.Property(type=str, default='')

    def __init__(self, data=None, pkg_type='formula', installed_set=None, **kwargs):
        super().__init__(**kwargs)
        if data:
            self._from_api(data, pkg_type, installed_set)

    def _from_api(self, data, pkg_type, installed_set=None):
        self.pkg_type = pkg_type
        if pkg_type == 'formula':
            self.name = data.get('name', '')
            self.full_name = data.get('full_name', self.name)
            self.display_name = self.name
            self.description = data.get('desc', '') or ''
            self.homepage = data.get('homepage', '') or ''
            versions = data.get('versions', {})
            self.version = versions.get('stable', '') or '' if isinstance(versions, dict) else ''
            self.license_ = data.get('license', '') or ''
        else:
            self.name = data.get('token', '')
            self.full_name = data.get('full_token', self.name)
            names = data.get('name', [])
            self.display_name = names[0] if names else self.name
            self.description = data.get('desc', '') or ''
            self.homepage = data.get('homepage', '') or ''
            self.version = data.get('version', '') or ''

        if installed_set:
            self.installed = self.name in installed_set or self.full_name in installed_set


class BrewBackend(GObject.Object):
    """Backend that communicates with both the Homebrew JSON API and local brew CLI."""

    __gtype_name__ = 'PasarBrewBackend'

    loading = GObject.Property(type=bool, default=False)

    __gsignals__ = {
        'formulae-loaded': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'casks-loaded': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'installed-loaded': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'operation-complete': (GObject.SignalFlags.RUN_LAST, None, (bool, str)),
        'operation-output': (GObject.SignalFlags.RUN_LAST, None, (str,)),
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._formulae = []
        self._casks = []
        self._installed_formulae = set()
        self._installed_casks = set()
        self._cache_dir = os.path.join(GLib.get_user_cache_dir(), 'pasar')
        os.makedirs(self._cache_dir, exist_ok=True)

    def parse_brewfile(self, path):
        import re
        taps = []
        formulae = []
        casks = []
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('tap '):
                        m = re.match(r'tap\s+["\']([^"\']+)["\']', line)
                        if m: taps.append(m.group(1))
                    elif line.startswith('brew '):
                        m = re.match(r'brew\s+["\']([^"\']+)["\']', line)
                        if m: formulae.append(m.group(1))
                    elif line.startswith('cask '):
                        m = re.match(r'cask\s+["\']([^"\']+)["\']', line)
                        if m: casks.append(m.group(1))
        except Exception as e:
            print(f"Pasar: Error parsing Brewfile: {e}")
        return {'taps': taps, 'formulae': formulae, 'casks': casks}


    @property
    def formulae(self):
        return self._formulae

    @property
    def casks(self):
        return self._casks

    def _fetch_json(self, url):
        """Fetch JSON from URL with a timeout."""
        req = Request(url, headers={'User-Agent': 'Pasar/0.1'})
        try:
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except (URLError, json.JSONDecodeError, Exception) as e:
            print(f'Pasar: Failed to fetch {url}: {e}')
            return None

    def _cache_path(self, name):
        return os.path.join(self._cache_dir, f'{name}.json')

    def _load_cached(self, name):
        path = self._cache_path(name)
        if os.path.exists(path):
            try:
                age = GLib.get_real_time() / 1e6 - os.path.getmtime(path)
                if age < 3600:  # 1 hour cache
                    with open(path) as f:
                        return json.load(f)
            except Exception:
                pass
        return None

    def _save_cache(self, name, data):
        try:
            with open(self._cache_path(name), 'w') as f:
                json.dump(data, f)
        except Exception:
            pass

    def _get_installed(self):
        """Get sets of installed formula and cask names."""
        formulae = set()
        casks = set()
        try:
            result = subprocess.run(
                _brew_cmd(['list', '--formula', '-1']),
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                formulae = set(result.stdout.strip().split('\n')) - {''}
        except Exception as e:
            print(f'Pasar: Failed to list installed formulae: {e}')

        try:
            result = subprocess.run(
                _brew_cmd(['list', '--cask', '-1']),
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                casks = set(result.stdout.strip().split('\n')) - {''}
        except Exception as e:
            print(f'Pasar: Failed to list installed casks: {e}')

        return formulae, casks

    def load_all_async(self):
        """Load all package data asynchronously."""
        self.loading = True
        thread = threading.Thread(target=self._load_all_thread, daemon=True)
        thread.start()

    def _load_all_thread(self):
        # Get installed packages first
        installed_f, installed_c = self._get_installed()
        self._installed_formulae = installed_f
        self._installed_casks = installed_c

        # Emit installed signal
        installed_pkgs = []
        GLib.idle_add(self.emit, 'installed-loaded', installed_pkgs)

        # Load formulae
        data = self._load_cached('formulae')
        if data is None:
            data = self._fetch_json(FORMULA_API)
            if data:
                self._save_cache('formulae', data)
        if data:
            self._formulae = [
                Package(d, 'formula', self._installed_formulae) for d in data
            ]
            GLib.idle_add(self.emit, 'formulae-loaded', self._formulae)

        # Load casks
        data = self._load_cached('casks')
        if data is None:
            data = self._fetch_json(CASK_API)
            if data:
                self._save_cache('casks', data)
        if data:
            import sys
            is_linux = sys.platform.startswith('linux')
            
            if is_linux:
                filtered_data = []
                for d in data:
                    depends_on = d.get('depends_on', {})
                    if 'macos' not in depends_on:
                        filtered_data.append(d)
                data = filtered_data

            self._casks = [
                Package(d, 'cask', self._installed_casks) for d in data
            ]
            GLib.idle_add(self.emit, 'casks-loaded', self._casks)

        GLib.idle_add(self._set_loading_false)

    def _set_loading_false(self):
        self.loading = False

    def search(self, query, pkg_type=None):
        """Search packages by name/description. Returns list of Package."""
        query = query.lower().strip()
        if not query:
            return []

        results = []
        if pkg_type in (None, 'formula'):
            for pkg in self._formulae:
                if query in pkg.name.lower() or query in pkg.description.lower():
                    results.append(pkg)
        if pkg_type in (None, 'cask'):
            for pkg in self._casks:
                if query in pkg.name.lower() or query in pkg.display_name.lower() or query in pkg.description.lower():
                    results.append(pkg)

        # Sort: exact name matches first, then starts-with, then contains
        def sort_key(pkg):
            n = pkg.name.lower()
            if n == query:
                return (0, n)
            if n.startswith(query):
                return (1, n)
            return (2, n)

        results.sort(key=sort_key)
        return results

    def get_installed_packages(self):
        """Return list of installed Package objects."""
        installed = []
        for pkg in self._formulae:
            if pkg.installed:
                installed.append(pkg)
        for pkg in self._casks:
            if pkg.installed:
                installed.append(pkg)
        return installed

    def install_async(self, package, callback=None):
        """Install a package asynchronously."""
        thread = threading.Thread(
            target=self._run_brew_operation,
            args=('install', package, callback),
            daemon=True,
        )
        thread.start()

    def remove_async(self, package, callback=None):
        """Remove a package asynchronously."""
        thread = threading.Thread(
            target=self._run_brew_operation,
            args=('uninstall', package, callback),
            daemon=True,
        )
        thread.start()

    def upgrade_async(self, package, callback=None):
        """Upgrade a package asynchronously."""
        thread = threading.Thread(
            target=self._run_brew_operation,
            args=('upgrade', package, callback),
            daemon=True,
        )
        thread.start()

    def _run_brew_operation(self, operation, package, callback=None):
        args = [operation]
        if package.pkg_type == 'cask':
            args.append('--cask')
        args.append(package.name)
        cmd = _brew_cmd(args)

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            output_lines = []
            for line in process.stdout:
                line = line.rstrip('\n')
                output_lines.append(line)
                GLib.idle_add(self.emit, 'operation-output', line)

            process.wait()
            success = process.returncode == 0

            if success:
                if operation == 'install':
                    package.installed = True
                    if package.pkg_type == 'formula':
                        self._installed_formulae.add(package.name)
                    else:
                        self._installed_casks.add(package.name)
                elif operation == 'uninstall':
                    package.installed = False
                    if package.pkg_type == 'formula':
                        self._installed_formulae.discard(package.name)
                    else:
                        self._installed_casks.discard(package.name)

            msg = '\n'.join(output_lines)
            GLib.idle_add(self.emit, 'operation-complete', success, msg)
            if callback:
                GLib.idle_add(callback, success, msg)

        except Exception as e:
            GLib.idle_add(self.emit, 'operation-complete', False, str(e))
            if callback:
                GLib.idle_add(callback, False, str(e))

    def get_package_info_async(self, package, callback):
        """Get detailed info for a package asynchronously."""
        thread = threading.Thread(
            target=self._get_package_info_thread,
            args=(package, callback),
            daemon=True,
        )
        thread.start()

    def _get_package_info_thread(self, package, callback):
        if package.pkg_type == 'formula':
            url = FORMULA_DETAIL_API.format(package.name)
        else:
            url = CASK_DETAIL_API.format(package.name)

        data = self._fetch_json(url)
        GLib.idle_add(callback, package, data)

    def fetch_icon_async(self, package, callback):
        """Try to fetch an icon for the package."""
        thread = threading.Thread(
            target=self._fetch_icon_thread,
            args=(package, callback),
            daemon=True,
        )
        thread.start()

    def _fetch_icon_thread(self, package, callback):
        """Try multiple icon sources for a package."""
        icon_path = os.path.join(self._cache_dir, f'icon_{package.name}.png')

        if os.path.exists(icon_path):
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(icon_path, 64, 64, True)
                GLib.idle_add(callback, package, pixbuf)
                return
            except Exception:
                pass

        # For casks, try to get icon from the homepage's favicon or known sources
        # Homebrew doesn't have built-in icon metadata, so we try common sources
        icon_urls = []
        
        icon_urls.append(f'https://raw.githubusercontent.com/hanthor/pasar-metadata/main/icons/{package.name}.png')

        if package.homepage:
            # Try DuckDuckGo favicon service (reliable, no API key needed)
            domain = package.homepage.replace('https://', '').replace('http://', '').split('/')[0]
            icon_urls.append(f'https://icons.duckduckgo.com/ip3/{domain}.ico')

        for url in icon_urls:
            try:
                req = Request(url, headers={'User-Agent': 'Pasar/0.1'})
                with urlopen(req, timeout=10) as resp:
                    data = resp.read()
                    if len(data) > 100:  # Not an error page
                        with open(icon_path, 'wb') as f:
                            f.write(data)
                        loader = GdkPixbuf.PixbufLoader()
                        loader.write(data)
                        loader.close()
                        pixbuf = loader.get_pixbuf()
                        if pixbuf:
                            pixbuf = pixbuf.scale_simple(64, 64, GdkPixbuf.InterpType.BILINEAR)
                            GLib.idle_add(callback, package, pixbuf)
                            return
            except Exception:
                continue

        GLib.idle_add(callback, package, None)

    def fetch_screenshot_async(self, package, callback):
        """Try to fetch a screenshot for the package."""
        thread = threading.Thread(
            target=self._fetch_screenshot_thread,
            args=(package, callback),
            daemon=True,
        )
        thread.start()

    def _fetch_screenshot_thread(self, package, callback):
        """Try to fetch a screenshot image for a package."""
        screenshot_path = os.path.join(self._cache_dir, f'screenshot_{package.name}.jpg')

        if os.path.exists(screenshot_path):
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(screenshot_path, 800, 600, True)
                GLib.idle_add(callback, package, pixbuf)
                return
            except Exception:
                pass

        url = f'https://raw.githubusercontent.com/hanthor/pasar-metadata/main/screenshots/{package.name}.jpg'
        try:
            req = Request(url, headers={'User-Agent': 'Pasar/0.1'})
            with urlopen(req, timeout=10) as resp:
                data = resp.read()
                if len(data) > 100:
                    with open(screenshot_path, 'wb') as f:
                        f.write(data)
                    loader = GdkPixbuf.PixbufLoader()
                    loader.write(data)
                    loader.close()
                    pixbuf = loader.get_pixbuf()
                    if pixbuf:
                        pixbuf = pixbuf.scale_simple(800, 600, GdkPixbuf.InterpType.BILINEAR)
                        GLib.idle_add(callback, package, pixbuf)
                        return
        except Exception:
            pass

        GLib.idle_add(callback, package, None)
