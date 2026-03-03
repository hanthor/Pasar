# test_search_provider.py - Tests for GNOME Shell Search Provider
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import os
import pytest

from gi.repository import Gio, GLib

from pasar.backend import Package
from pasar.search_provider import PasarSearchProvider


def test_build_search_provider_cache(tmp_path, fresh_logging, monkeypatch):
    """Test that the backend correctly builds the search provider cache."""
    from pasar.backend import BrewBackend
    
    # Mock system platform to test linux filtering
    monkeypatch.setattr('sys.platform', 'linux')
    
    backend = BrewBackend()
    backend._cache_dir = str(tmp_path)
    
    # Add some mock packages
    backend._formulae = [
        Package({
            'name': 'ripgrep',
            'desc': 'Fast grep alternative',
            'versions': {'stable': '14.1'}
        }, 'formula')
    ]
    
    backend._casks = [
        Package({
            'token': 'firefox',
            'name': ['Mozilla Firefox'],
            'desc': 'Web browser'
        }, 'cask'),
        # Casks that are macOS only should not be in the cache if filtered properly
    ]
    
    # Build cache
    backend._build_search_provider_cache()
    
    cache_path = os.path.join(str(tmp_path), 'linux_packages.json')
    assert os.path.exists(cache_path)
    
    with open(cache_path, 'r') as f:
        data = json.load(f)
        
    assert len(data) == 2
    
    rg = next(p for p in data if p['name'] == 'ripgrep')
    assert rg['pkg_type'] == 'formula'
    assert rg['description'] == 'Fast grep alternative'
    
    ff = next(p for p in data if p['name'] == 'firefox')
    assert ff['pkg_type'] == 'cask'
    assert ff['display_name'] == 'Mozilla Firefox'


def test_search_provider_logic(tmp_path, fresh_logging):
    """Test the search logic of the SearchProvider."""
    # Write a mock cache file
    cache_dir = os.path.join(GLib.get_user_cache_dir(), 'pasar')
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, 'linux_packages.json')
    
    test_data = [
        {'name': 'ripgrep', 'display_name': 'ripgrep', 'description': 'Search tool', 'pkg_type': 'formula'},
        {'name': 'grep', 'display_name': 'grep', 'description': 'Standard grep', 'pkg_type': 'formula'},
        {'name': 'postgresql', 'display_name': 'postgresql', 'description': 'Relational database', 'pkg_type': 'formula'},
        {'name': 'firefox', 'display_name': 'Mozilla Firefox', 'description': 'Web browser', 'pkg_type': 'cask'},
    ]
    
    with open(cache_path, 'w') as f:
        json.dump(test_data, f)
        
    # Create provider (mock application)
    class MockApp:
        def __init__(self):
            self.actions = []
        def activate_action(self, name, param):
            self.actions.append((name, param.get_string()))
            
    app = MockApp()
    provider = PasarSearchProvider(app)
    
    # Test search
    results = provider._search(["grep"])
    # "grep" exact match should be first, then "ripgrep"
    assert results == ["grep", "ripgrep"]
    
    results = provider._search(["fire"])
    assert results == ["firefox"]
    
    results = provider._search(["SQL"])
    assert results == ["postgresql"]
    
    # Cleanup
    if os.path.exists(cache_path):
        os.remove(cache_path)
