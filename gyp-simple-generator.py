import os
import sys
import json

GENERATED = '${CMAKE_BINARY_DIR}/generated_%%ncg_guid%%'
BLOB_FILE = './all_platforms_build_blob.json'

def get_OS():
    if sys.platform == 'darwin':
        return 'mac'

    if sys.platform.startswith('linux'):
        return 'linux'

    if sys.platform == 'win32':
        return 'win32'

    # TBD: implement windows
    raise RuntimeError('Unknown platform: {}'.format(sys.platform))

generator_default_variables = {
    'OS': get_OS(),

    'PRODUCT_DIR':             '${CMAKE_CURRENT_BINARY_DIR}',
    'SHARED_INTERMEDIATE_DIR':  GENERATED,
    'INTERMEDIATE_DIR':        '${CMAKE_CURRENT_BINARY_DIR}',

    'EXECUTABLE_PREFIX': '',
    'EXECUTABLE_SUFFIX': '${CMAKE_EXECUTABLE_SUFFIX}',
    'STATIC_LIB_PREFIX': '${CMAKE_STATIC_LIBRARY_PREFIX}',
    'STATIC_LIB_SUFFIX': '${CMAKE_STATIC_LIBRARY_SUFFIX}',
    'SHARED_LIB_PREFIX': '${CMAKE_SHARED_LIBRARY_PREFIX}',
    'SHARED_LIB_SUFFIX': '${CMAKE_SHARED_LIBRARY_SUFFIX}',
}

class BuildBlobEncoder(json.JSONEncoder):
    def default(self, data):
        if type(data) == set:
            data = list(data)
            return data

        if data.__class__.__name__ == 'Values':
            data = data.__dict__
            return data

        return json.JSONEncoder.default(self, data)


def GenerateOutput(names, targets, data, params):
    build_blob = {}
    if os.path.isfile(BLOB_FILE):
        with open(BLOB_FILE, 'r') as f:
            build_blob = json.load(f)

    build_blob[sys.platform] = {
        'names'    : names,
        'targets'  : targets,
        'data'     : data,
        'params'   : params,
    }

    with open(BLOB_FILE, 'w') as f:
        json.dump(build_blob, f, indent=4, cls=BuildBlobEncoder)

