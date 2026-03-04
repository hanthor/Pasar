desktop_file = i18n.merge_file(
  input: 'dev.hanthor.Pasar.desktop.in',
  output: 'dev.hanthor.Pasar.desktop',
  type: 'desktop',
  po_dir: '../po',
  install: true,
  install_dir: get_option('datadir') / 'applications',
)

appstream_file = i18n.merge_file(
  input: 'dev.hanthor.Pasar.metainfo.xml.in',
  output: 'dev.hanthor.Pasar.metainfo.xml',
  po_dir: '../po',
  install: true,
  install_dir: get_option('datadir') / 'metainfo',
)

install_data(
  'dev.hanthor.Pasar.gschema.xml',
  install_dir: get_option('datadir') / 'glib-2.0' / 'schemas',
)

install_data(
  'dev.hanthor.Pasar-mime.xml',
  install_dir: get_option('datadir') / 'mime' / 'packages',
)

install_data(
  'icons/hicolor/scalable/apps/dev.hanthor.Pasar.svg',
  install_dir: get_option('datadir') / 'icons' / 'hicolor' / 'scalable' / 'apps',
)

install_data(
  'icons/hicolor/symbolic/apps/dev.hanthor.Pasar-symbolic.svg',
  install_dir: get_option('datadir') / 'icons' / 'hicolor' / 'symbolic' / 'apps',
)
install_data(
  'dev.hanthor.Pasar.search-provider.ini.in',
  rename: 'dev.hanthor.Pasar.search-provider.ini',
  install_dir: get_option('datadir') / 'gnome-shell' / 'search-providers'
)

service_conf = configuration_data()
service_conf.set('bindir', get_option('prefix') / get_option('bindir'))
configure_file(
  input: 'dev.hanthor.Pasar.service.in',
  output: 'dev.hanthor.Pasar.service',
  configuration: service_conf,
  install_dir: get_option('datadir') / 'dbus-1' / 'services'
)
