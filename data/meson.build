desktop_file = i18n.merge_file(
  input: 'dev.jamesq.Pasar.desktop.in',
  output: 'dev.jamesq.Pasar.desktop',
  type: 'desktop',
  po_dir: '../po',
  install: true,
  install_dir: get_option('datadir') / 'applications',
)

appstream_file = i18n.merge_file(
  input: 'dev.jamesq.Pasar.metainfo.xml.in',
  output: 'dev.jamesq.Pasar.metainfo.xml',
  po_dir: '../po',
  install: true,
  install_dir: get_option('datadir') / 'metainfo',
)

install_data(
  'dev.jamesq.Pasar.gschema.xml',
  install_dir: get_option('datadir') / 'glib-2.0' / 'schemas',
)

install_data(
  'icons/hicolor/scalable/apps/dev.jamesq.Pasar.svg',
  install_dir: get_option('datadir') / 'icons' / 'hicolor' / 'scalable' / 'apps',
)

install_data(
  'icons/hicolor/symbolic/apps/dev.jamesq.Pasar-symbolic.svg',
  install_dir: get_option('datadir') / 'icons' / 'hicolor' / 'symbolic' / 'apps',
)
