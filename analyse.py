import os
import sys
import json

GENERATED = '${CMAKE_BINARY_DIR}/ncg_generated'
ANALYSIS_FILE = './gyp_analysis.json'

def get_OS():
    if sys.platform == 'darwin':
        return 'mac'

    if sys.platform.startswith('linux'):
        return 'linux'

    if sys.platform == 'win32':
        return 'win32'

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

    'CONFIGURATION_NAME': '${CMAKE_BUILD_TYPE}'
}

class AnalysisEncoder(json.JSONEncoder):
    def default(self, data):
        if type(data) == set:
            data = list(data)
            return data

        if data.__class__.__name__ == 'Values':
            data = data.__dict__
            return data

        return json.JSONEncoder.default(self, data)

def unqualify_path(path, working_directory):
    '''
    Extract the relative path for use in creating a target
    cmake file. GYP generates differing working directory/path
    data on windows vs linux/darwin:

    windows path: \\folder\\file:targetname#target
    windiws working dir: \\path\\to\\nodesrc
    linux/darwin path: /path/to/nodesrc/folder/file:targetname#target
    linux/darwin working dir: /path/to/nodesrc

    Desired output: /folder/file:targetname#target
    '''
    if sys.platform == 'win32':
        return path.replace('\\', '/')

    split_path = path.split(':')
    path       = split_path[0]
    target     = split_path[1]

    unqualified_path = os.path.dirname(os.path.relpath(path,
                                                       working_directory))
    file_name = os.path.basename(path)
    if unqualified_path == '':
        return file_name + ':' + target
    return unqualified_path + '/' + file_name + ':' + target

def normalize_target_paths(targets, work_dir):
    new_targets = {}
    for key, value in targets.iteritems():
        # First, turn aboslute paths in dependencies/original_dependencies
        # into relative paths from the nodesrc directory
        if 'dependencies' in value:
            value['dependencies'] = [unqualify_path(dep, work_dir) for dep in \
            value['dependencies']]

        if 'dependencies_original' in value:
            value['dependencies_original'] = [unqualify_path(dep, work_dir) for \
            dep in value['dependencies_original']]

        # Turn the path specified in the target key into a relative path
        new_targets[unqualify_path(key, work_dir)] = value

    return new_targets

def analyze(targets):
    executables           = set()
    generated_libraries   = set()
    interface_libraries   = set()
    all_generated_sources = set()

    for name, target in targets.iteritems():
        for action in target.get('actions', []):
            if action.get('process_outputs_as_sources', False):
                for output in action.get('outputs', []):
                    if 'sources' not in target:
                        target['sources'] = []
                    target['sources'].append(output)

        if target['type'] == 'executable':
            executables.add(name)
        if 'sources' not in target or all(s.endswith('.h') for s in target.get('sources', [])):
            produces_sources = False
            for action in target.get('actions', []):
                if action.get('process_outputs_as_sources', False):
                    produces_sources = True
                for output in action.get('outputs', []):
                    if output.startswith(GENERATED):
                        all_generated_sources.add(output)
            if target['type'] in {'shared_library', 'static_library'} and \
                                                              produces_sources:
                generated_libraries.add(name)
            else:
                interface_libraries.add(name)

    return {
        'executables':           executables,
        'generated_libraries':   generated_libraries,
        'interface_libraries':   interface_libraries,
        'all_generated_sources': all_generated_sources,
    }

def GenerateOutput(names, targets, data, params):
    targets = normalize_target_paths(targets, params['cwd'])

    analysis_data = {}
    if os.path.isfile(ANALYSIS_FILE):
        with open(ANALYSIS_FILE, 'r') as f:
            analysis_data = json.load(f)

    analysis_data[sys.platform] = {
        'targets'  : targets,
        'analysis' : analyze(targets)
    }

    with open(ANALYSIS_FILE, 'w') as f:
        json.dump(analysis_data, f,
                  sort_keys=True,
                  separators=(',', ': '),
                  indent=4,
                  cls=AnalysisEncoder)

