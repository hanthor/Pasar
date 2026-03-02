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
            # Stable source URL — often a github.com release tarball, very reliable for
            # finding the upstream repo even when homepage is a custom domain.
            urls = data.get('urls', {})
            stable = urls.get('stable', {}) if isinstance(urls, dict) else {}
            self.source_url = stable.get('url', '') or '' if isinstance(stable, dict) else ''
        else:
            self.name = data.get('token', '')
            self.full_name = data.get('full_token', self.name)
            names = data.get('name', [])
            self.display_name = names[0] if names else self.name
            self.description = data.get('desc', '') or ''
            self.homepage = data.get('homepage', '') or ''
            self.version = data.get('version', '') or ''
            # Cask download URL — often a github.com release asset
            self.source_url = data.get('url', '') or ''

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
                with open(path) as f:
                    data = json.load(f)
                return data, age > 3600  # Return data and whether it's stale
            except Exception:
                pass
        return None, True

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
        # Core API fetch thread
        thread = threading.Thread(target=self._load_all_thread, daemon=True)
        thread.start()
        # Tap packages are all on disk — start loading immediately in parallel
        tap_thread = threading.Thread(target=self._load_tap_packages, daemon=True)
        tap_thread.start()

    def _load_all_thread(self):
        # Get installed packages first
        installed_f, installed_c = self._get_installed()
        self._installed_formulae = installed_f
        self._installed_casks = installed_c

        # Emit installed signal
        installed_pkgs = []
        GLib.idle_add(self.emit, 'installed-loaded', installed_pkgs)

        # Load formulae from cache first
        data, is_stale = self._load_cached('formulae')
        if data:
            self._formulae = [
                Package(d, 'formula', self._installed_formulae) for d in data
            ]
            GLib.idle_add(self.emit, 'formulae-loaded', self._formulae)

        # Fetch in background if missing or stale
        if not data or is_stale:
            new_data = self._fetch_json(FORMULA_API)
            if new_data:
                self._save_cache('formulae', new_data)
                self._formulae = [
                    Package(d, 'formula', self._installed_formulae) for d in new_data
                ]
                GLib.idle_add(self.emit, 'formulae-loaded', self._formulae)

        # Load casks from cache first
        data, is_stale = self._load_cached('casks')
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

        # Fetch in background if missing or stale
        if not data or is_stale:
            new_data = self._fetch_json(CASK_API)
            if new_data:
                self._save_cache('casks', new_data)
                
                import sys
                is_linux = sys.platform.startswith('linux')
                
                if is_linux:
                    filtered_data = []
                    for d in new_data:
                        depends_on = d.get('depends_on', {})
                        if 'macos' not in depends_on:
                            filtered_data.append(d)
                    new_data = filtered_data

                self._casks = [
                    Package(d, 'cask', self._installed_casks) for d in new_data
                ]
                GLib.idle_add(self.emit, 'casks-loaded', self._casks)

        GLib.idle_add(self._set_loading_false)


    def _load_tap_packages(self):
        """
        Enumerate all installed taps directly from the filesystem (instantaneous)
        instead of running `brew tap-info` which takes 10+ seconds.
        Then load formulae and casks from the local tap directories.
        """
        brew_repo_candidates = [
            '/home/linuxbrew/.linuxbrew/Homebrew',
            '/var/home/linuxbrew/.linuxbrew/Homebrew',
            '/opt/homebrew',
            '/usr/local/Homebrew'
        ]
        taps_dir = None
        for cand in brew_repo_candidates:
            d = os.path.join(cand, 'Library', 'Taps')
            if os.path.isdir(d):
                taps_dir = d
                break

        if not taps_dir:
            return

        tap_list = []
        try:
            for user in os.listdir(taps_dir):
                user_dir = os.path.join(taps_dir, user)
                if not os.path.isdir(user_dir): continue
                for repo in os.listdir(user_dir):
                    if not repo.startswith('homebrew-'): continue
                    repo_dir = os.path.join(user_dir, repo)
                    tap_name = f'{user}/{repo[9:]}'
                    tap_list.append({'name': tap_name, 'path': repo_dir})
        except Exception as e:
            print(f'Pasar: Failed to list taps directory: {e}')
            return

        import sys
        is_linux = sys.platform.startswith('linux')

        # Core tap is already handled by the API — skip it
        CORE_TAPS = {'homebrew/core', 'homebrew/cask'}

        new_formulae = list(self._formulae)
        new_casks = list(self._casks)
        existing_formula_names = {p.name for p in self._formulae}
        existing_cask_names = {p.name for p in self._casks}
        formulae_changed = False
        casks_changed = False

        for tap in tap_list:
            tap_name = tap['name']
            if tap_name in CORE_TAPS:
                continue

            tap_path = tap['path']
            if not tap_path or not os.path.isdir(tap_path):
                continue


            # ── Formulae ─────────────────────────────────────────────────────
            formula_dir = os.path.join(tap_path, 'Formula')
            if os.path.isdir(formula_dir):
                for fname in os.listdir(formula_dir):
                    if not fname.endswith('.rb'):
                        continue
                    pkg_name = fname[:-3]  # strip .rb
                    if pkg_name in existing_formula_names:
                        continue
                    # Build a minimal data dict from what we can extract cheaply
                    # (avoid running `brew info` per-formula — too slow at scale)
                    data = self._minimal_formula_data_from_rb(
                        os.path.join(formula_dir, fname), tap_name, pkg_name
                    )
                    if data:
                        pkg = Package(data, 'formula', self._installed_formulae)
                        new_formulae.append(pkg)
                        existing_formula_names.add(pkg_name)
                        formulae_changed = True

            # ── Casks ─────────────────────────────────────────────────────────
            for cask_dir_name in ('Casks', 'cask'):
                cask_dir = os.path.join(tap_path, cask_dir_name)
                if os.path.isdir(cask_dir):
                    for fname in os.listdir(cask_dir):
                        if not fname.endswith('.rb'):
                            continue
                        pkg_name = fname[:-3]
                        if pkg_name in existing_cask_names:
                            continue
                        data = self._minimal_cask_data_from_rb(
                            os.path.join(cask_dir, fname), tap_name, pkg_name
                        )
                        if data:
                            # Filter macOS-only casks on Linux
                            if is_linux and 'macos' in data.get('depends_on', {}):
                                continue
                            pkg = Package(data, 'cask', self._installed_casks)
                            new_casks.append(pkg)
                            existing_cask_names.add(pkg_name)
                            casks_changed = True

        if formulae_changed:
            self._formulae = new_formulae
            GLib.idle_add(self.emit, 'formulae-loaded', self._formulae)

        if casks_changed:
            self._casks = new_casks
            GLib.idle_add(self.emit, 'casks-loaded', self._casks)

    def _minimal_formula_data_from_rb(self, rb_path, tap_name, pkg_name):
        """
        Extract minimal metadata from a .rb formula file using simple regex,
        fast enough to run for tens/hundreds of formulae without noticeable delay.
        Returns a dict compatible with Package._from_api or None on failure.
        """
        import re
        try:
            with open(rb_path, 'r', encoding='utf-8', errors='replace') as f:
                src = f.read(8192)  # Only need the header section
        except Exception:
            return None

        def extract(pattern, default=''):
            m = re.search(pattern, src, re.MULTILINE)
            return m.group(1).strip() if m else default

        desc = extract(r'^\s*desc\s+["\']([^"\']+)["\']')
        homepage = extract(r'^\s*homepage\s+["\']([^"\']+)["\']')
        version = extract(r'^\s*version\s+["\']([^"\']+)["\']') or \
                  extract(r'tag:\s+["\']v?([^"\']+)["\']')
        url = extract(r'^\s*url\s+["\']([^"\']+)["\']')
        license_ = extract(r'^\s*license\s+["\']([^"\']+)["\']')

        return {
            'name': pkg_name,
            'full_name': f'{tap_name}/{pkg_name}',
            'desc': desc,
            'homepage': homepage,
            'versions': {'stable': version},
            'license': license_,
            'urls': {'stable': {'url': url}},
        }

    def _minimal_cask_data_from_rb(self, rb_path, tap_name, pkg_name):
        """Same as _minimal_formula_data_from_rb but for cask .rb files."""
        import re
        try:
            with open(rb_path, 'r', encoding='utf-8', errors='replace') as f:
                src = f.read(8192)
        except Exception:
            return None

        def extract(pattern, default=''):
            m = re.search(pattern, src, re.MULTILINE)
            return m.group(1).strip() if m else default

        version = extract(r'^\s*version\s+["\']([^"\']+)["\']')
        name_extracted = extract(r'^\s*name\s+["\']([^"\']+)["\']')
        desc = extract(r'^\s*desc\s+["\']([^"\']+)["\']')
        homepage = extract(r'^\s*homepage\s+["\']([^"\']+)["\']')
        url = extract(r'^\s*url\s+["\']([^"\']+)["\']')

        # Detect macOS dependencies: only_if builds, requires_zap 'macos' etc.
        depends_on = {}
        if 'macos' in src.lower():
            ma = re.search(r'depends_on\s+macos:', src)
            if ma:
                depends_on['macos'] = True

        name_m = re.search(r'cask\s+["\']([^"\']+)["\']', src)
        token = name_m.group(1) if name_m else pkg_name

        cask_names = [name_extracted] if name_extracted else ([desc] if desc else [token])

        return {
            'token': token,
            'full_token': f'{tap_name}/{token}',
            'name': cask_names,
            'desc': desc,
            'homepage': homepage,
            'version': version,
            'url': url,
            'depends_on': depends_on,
        }



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

        icon_urls = []

        # 1. Scrape the homepage HTML for the best available favicon
        if package.homepage:
            favicon_url = self._find_favicon_url(package.homepage)
            if favicon_url:
                icon_urls.append(favicon_url)

        # 2. First image from source repo README (good for projects with logo images)
        readme_images = self._fetch_readme_images(package)
        if readme_images:
            icon_urls.append(readme_images[0])

        # 3. DuckDuckGo favicon service — reliable last resort
        if package.homepage:
            domain = package.homepage.replace('https://', '').replace('http://', '').split('/')[0]
            icon_urls.append(f'https://icons.duckduckgo.com/ip3/{domain}.ico')

        for url in icon_urls:
            try:
                req = Request(url, headers={'User-Agent': 'Pasar/0.1'})
                with urlopen(req, timeout=10) as resp:
                    data = resp.read()
                    if len(data) > 200:  # Filter out 1x1 pixel / blank responses
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

    def _find_favicon_url(self, homepage):
        """
        Fetch the homepage HTML and return the best favicon URL found, or None.

        Priority order:
          1. apple-touch-icon (usually 180×180 PNG — best quality)
          2. icon with PNG/ICO type
          3. shortcut icon
          4. /favicon.png directly
          5. /favicon.ico directly
        """
        import re
        try:
            req = Request(homepage, headers={'User-Agent': 'Mozilla/5.0 Pasar/0.1'})
            with urlopen(req, timeout=8) as resp:
                # Only read the <head> — stop after 32 KB to avoid downloading full pages
                chunk = resp.read(32768).decode('utf-8', errors='replace')
        except Exception:
            return None

        # Parse origin from the URL for resolving relative paths
        from urllib.parse import urljoin

        # Collect all <link> icon tags
        links = re.findall(
            r'<link\s[^>]*rel=["\']([^"\']*)["\'][^>]*href=["\']([^"\']+)["\']'
            r'|<link\s[^>]*href=["\']([^"\']+)["\'][^>]*rel=["\']([^"\']*)["\']',
            chunk, re.IGNORECASE
        )

        candidates = []
        for m in links:
            rel = (m[0] or m[3]).lower()
            href = m[1] or m[2]
            if not href or href.startswith('data:'):
                continue
            url = urljoin(homepage, href)
            if 'apple-touch-icon' in rel:
                candidates.append((0, url))  # Highest priority
            elif 'icon' in rel and href.lower().endswith('.png'):
                candidates.append((1, url))
            elif 'icon' in rel and href.lower().endswith('.ico'):
                candidates.append((2, url))
            elif 'icon' in rel:
                candidates.append((3, url))

        if candidates:
            candidates.sort(key=lambda x: x[0])
            return candidates[0][1]

        # Fall back to root-relative well-known paths
        from urllib.parse import urlparse
        parsed = urlparse(homepage)
        base = f'{parsed.scheme}://{parsed.netloc}'
        for path in ('/favicon.png', '/favicon.ico'):
            url = base + path
            try:
                req = Request(url, headers={'User-Agent': 'Pasar/0.1'})
                with urlopen(req, timeout=5) as resp:
                    if resp.status == 200 and int(resp.headers.get('Content-Length', '9999')) > 200:
                        return url
            except Exception:
                continue

        return None



    def fetch_screenshot_async(self, package, callback):
        """Try to fetch a screenshot for the package."""
        thread = threading.Thread(
            target=self._fetch_screenshot_thread,
            args=(package, callback),
            daemon=True,
        )
        thread.start()

    def fetch_readme_async(self, package, callback):
        """Fetch the README text for a package from its GitHub source repo."""
        thread = threading.Thread(
            target=self._fetch_readme_thread,
            args=(package, callback),
            daemon=True,
        )
        thread.start()

    def _fetch_readme_thread(self, package, callback):
        import re
        GH_RE = re.compile(r'github\.com/([^/\s"\']+)/([^/\s"\'#?.]+)')

        owner, repo = None, None
        for candidate in (getattr(package, 'source_url', ''), package.homepage or ''):
            if not candidate:
                continue
            m = GH_RE.search(candidate)
            if m:
                o, r = m.group(1), m.group(2).rstrip('.git')
                if o.lower() not in ('releases', 'downloads', 'mirrors', 'raw', 'orgs', 'users'):
                    owner, repo = o, r
                    break

        if not owner:
            GLib.idle_add(callback, package, None)
            return

        text = None
        for readme_name in ('README.md', 'readme.md', 'Readme.md', 'README.rst', 'README'):
            raw_url = f'https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{readme_name}'
            try:
                req = Request(raw_url, headers={'User-Agent': 'Pasar/0.1'})
                with urlopen(req, timeout=15) as resp:
                    text = resp.read().decode('utf-8', errors='replace')
                break
            except Exception:
                continue

        GLib.idle_add(callback, package, text)



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

        screenshot_urls = []

        # 1. pasar-metadata repo (curated)
        screenshot_urls.append(f'https://raw.githubusercontent.com/hanthor/pasar-metadata/main/screenshots/{package.name}.jpg')

        # 2. README images from source repo (skip the first one — that's the icon)
        readme_images = self._fetch_readme_images(package)
        if readme_images and len(readme_images) > 1:
            # Second image onwards are typically screenshots
            screenshot_urls.extend(readme_images[1:4])

        for url in screenshot_urls:
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
                continue

        GLib.idle_add(callback, package, None)

    def _fetch_readme_images(self, package):
        """
        Extract absolute image URLs from the project's GitHub README.

        Returns a list of image URLs (may be empty). Results are cached
        on the Package object to avoid duplicate network hits when both
        the icon and screenshot threads run.
        """
        import re

        # Cache on the package object so icon + screenshot threads share the result
        cached = getattr(package, '_readme_images', None)
        if cached is not None:
            return cached

        package._readme_images = []  # mark as attempted

        GH_RE = re.compile(r'github\.com/([^/\s"\']+)/([^/\s"\'#?.]+)')

        owner, repo = None, None
        # source_url (stable tarball) is the most reliable source — check it first.
        # It's a direct GitHub archive/releases URL for the vast majority of formulae.
        for candidate in (getattr(package, 'source_url', ''), package.homepage or ''):
            if not candidate:
                continue
            m = GH_RE.search(candidate)
            if m:
                o = m.group(1)
                r = m.group(2).rstrip('.git')
                # Skip well-known non-project paths
                if o.lower() in ('releases', 'downloads', 'mirrors', 'raw', 'orgs', 'users'):
                    continue
                owner, repo = o, r
                break

        if not owner:
            return []

        # Try common README filenames in order
        text = None
        for readme_name in ('README.md', 'readme.md', 'Readme.md', 'README.rst'):
            raw_url = f'https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{readme_name}'
            try:
                req = Request(raw_url, headers={'User-Agent': 'Pasar/0.1'})
                with urlopen(req, timeout=10) as resp:
                    text = resp.read().decode('utf-8', errors='replace')
                break
            except Exception:
                continue

        if not text:
            return []

        # Extract markdown image syntax:  ![alt](url)
        # and HTML <img src="url"> tags
        md_images = re.findall(r'!\[.*?\]\(([^)]+)\)', text)
        html_images = re.findall(r"""<img\s[^>]*src=["']([^"']+)["']""", text, re.IGNORECASE)
        all_images = md_images + html_images

        # Resolve relative URLs to absolute GitHub raw URLs
        base_raw = f'https://raw.githubusercontent.com/{owner}/{repo}/HEAD/'

        absolute = []
        for img in all_images:
            img = img.strip()
            if not img:
                continue
            if img.startswith('http://') or img.startswith('https://'):
                url = img
            elif img.startswith('./'):
                url = base_raw + img[2:]
            elif img.startswith('/'):
                url = base_raw + img[1:]
            else:
                url = base_raw + img

            # Skip badge/shield images — not useful as icons or screenshots
            low = url.lower()
            if any(skip in low for skip in ('shields.io', 'badge', 'travis-ci', 'codecov',
                                             'appveyor', 'circleci', 'github/workflow',
                                             'actions/workflows', 'buymeacoffee',
                                             'ko-fi', 'opencollective')):
                continue
            # Skip SVG files — GdkPixbuf can't reliably load arbitrary SVGs
            if low.endswith('.svg'):
                continue

            absolute.append(url)

        package._readme_images = absolute
        return absolute

