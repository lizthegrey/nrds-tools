from distutils.core import setup
import py2exe
import sys

if len(sys.argv) == 1:
  sys.argv.append('py2exe')

icon_resources = []
if os.path.exists('icon.ico'):
  icon_resources.append((1, "icon.ico"))

setup(windows=[{'script': 'KosLookupExe.py',
                'icon_resources': icon_resources}],
    options={'py2exe': {'dll_excludes': ['MSVCP90.dll'],
                        'bundle_files': 1}},
    bundle_files=1,
    zipfile=None)

