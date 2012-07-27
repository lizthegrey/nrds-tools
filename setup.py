from distutils.core import setup
import py2exe

setup(windows=['KosLookupExe.py'],
    options={'py2exe': {'dll_excludes': ['MSVCP90.dll'],
                        'bundle_files': 1}},
    bundle_files=1,
    zipfile=None)

