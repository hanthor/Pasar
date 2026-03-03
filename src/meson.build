pkgdatadir = PKGDATADIR

blueprints = custom_target('blueprints',
  input: files(
    'window.blp',
    'package-tile.blp',
    'package-rich-tile.blp',
    'package-details.blp',
    'search-page.blp',
    'browse-page.blp',
    'installed-page.blp',
    'task-panel.blp',
    'brewfile-dialog.blp',
  ),
  output: '.',
  command: [
    find_program('blueprint-compiler'),
    'batch-compile',
    '@OUTPUT@',
    '@CURRENT_SOURCE_DIR@',
    '@INPUT@',
  ],
)

gnome.compile_resources('pasar',
  'pasar.gresource.xml',
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,
  dependencies: blueprints,
)

configure_file(
  input: 'pasar.in',
  output: 'pasar',
  configuration: conf,
  install: true,
  install_dir: get_option('bindir'),
  install_mode: 'rwxr-xr-x',
)

# Install Python sources
pasar_sources = [
  '__init__.py',
  'main.py',
  'application.py',
  'logging_util.py',
  'window.py',
  'backend.py',
  'package_tile.py',
  'package_rich_tile.py',
  'package_details.py',
  'search_page.py',
  'browse_page.py',
  'installed_page.py',
  'task_manager.py',
  'task_panel.py',
  'global_progress.py',
  'brewfile_dialog.py',
  'search_provider.py'
]

install_data(pasar_sources, install_dir: pkgdatadir / 'pasar')

install_data(
  'shell-search-provider-dbus-interfaces.xml',
  install_dir: pkgdatadir
)
