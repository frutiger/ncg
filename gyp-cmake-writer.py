from __future__ import print_function

import binascii
import os
import sys
import json
import pprint
import textwrap

from collections import defaultdict

import gyp.xcode_emulation

ANALYSIS_FILE = 'gyp_analysis.json'

CONFIGURATIONS = {'Debug', 'Release'}
KNOWN_TARGET_TYPES = {'shared_library', 'static_library', 'executable', 'none'}
SOURCE_CATEGORIES = {
    '.c':   'c',
    '.cc':  'cc',
    '.cpp': 'cc',
    '.cxx': 'cc',
}
GENERATED_GUID = '{}'.format(binascii.b2a_hex(os.urandom(16)))
GENERATED = '${CMAKE_BINARY_DIR}/generated_%%ncg_guid%%'

def get_OS():
    if sys.platform == 'darwin':
        return 'mac'

    if sys.platform.startswith('linux'):
        return 'linux'

    # TBD: implement windows
    raise RuntimeError('Unknown platform: {}'.format(sys.platform))

def get_CMake_OS(OS):
    if OS.startswith('linux'):
        return 'Linux'

    if OS == 'win32':
        return 'Windows'

    if OS == 'darwin':
        return 'Darwin'

    raise RuntimeError('Unknown platform: {}'.format(OS))

def xcode_flags_factories(xcode):
    def get_factory(category):
        def get_flags(configuration_name, _):
            if configuration_name is None:
                return []

            flags = []
            if category == 'c':
                flags += xcode.GetCflagsC(configuration_name)
            elif category == 'cc':
                flags += xcode.GetCflagsCC(configuration_name)
            else:
                raise RuntimeError('Unknown category: ' + category)
            flags += xcode.GetCflags(configuration_name)

            return flags
        return get_flags
    return get_factory

def generic_flags_factories():
    def get_factory(category):
        def get_flags(configuration_name, configuration):
            if configuration_name is None:
                return []

            flags = []
            if category == 'c':
                flags += configuration.get('cflags_c', [])
            elif category == 'cc':
                flags += configuration.get('cflags_cc', [])
            else:
                raise RuntimeError('Unknown category: ' + category)
            flags += configuration.get('cflags', [])

            return flags
        return get_flags
    return get_factory

def get_flags_factories(target):
    if sys.platform == 'darwin':
        return xcode_flags_factories(gyp.xcode_emulation.XcodeSettings(target))

    if sys.platform == 'win32':
        # TBD: implement for win32
        raise RuntimeError('Currently unsupported platform: ' + sys.platform)

    return generic_flags_factories()

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

class Writer(object):
    def __init__(self, file):
        self._file         = file
        self._interfaces   = set()
        self._indent_level = 0

    def _write(self, *args, **kwargs):
        indentation = ''.join(' ' for i in range(self._indent_level))
        args = [indentation + arg.replace('%%ncg_guid%%', GENERATED_GUID) for arg in args]
        print(*args, file=self._file, **kwargs)

    def _exposure(self, unqualified_name, property_name):
        if property_name in {'add_dependencies'}:
            return ''
        if unqualified_name in self._interfaces:
            return ' INTERFACE'
        if property_name in {'target_link_libraries'}:
            return ' PUBLIC'
        return ' PRIVATE'

    def platform_start(self, platform):
        self._write('if(CMAKE_SYSTEM_NAME STREQUAL {})'.format(platform))
        self._indent_level += 4

    def platform_end(self):
        self._indent_level -= 4
        self._write('endif()')

    def properties(self, property_name, target_name, properties):
        if len(properties) == 0:
            return

        self._write('{}('.format(property_name))
        self._write('    {}{}'.format(target_name,
                                      self._exposure(target_name,
                                                     property_name)))
        for property in properties:
            self._write('    {}'.format(property))
        self._write(')\n')

    def configuration_properties(self,
                                 property_name,
                                 target_name,
                                 configuration_name,
                                 properties):
        if len(properties) == 0:
            return

        self._write('if(CMAKE_BUILD_TYPE STREQUAL "{}")'.format(configuration_name))
        self._write('    {}('.format(property_name))
        self._write('        {}{}'.format(target_name, self._exposure(target_name,
                                                                      property_name)))
        for property in properties:
            if property != '':
                self._write('        {}'.format(property))
        self._write('    )')
        self._write('endif()\n')

    def custom_command(self, inputs, action, outputs):
        self._write('add_custom_command(')
        self._write('    OUTPUT {}'.format(' '.join(outputs)))
        self._write('    DEPENDS {}'.format(' '.join(inputs)))
        self._write('    COMMAND {}'.format(' '.join(action)))
        self._write('    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}')
        self._write(')\n')

    def library_with_actions(self, unqualified_name, sources):
        self._write('add_library(')
        self._write('    {}'.format(unqualified_name))
        self._write('    EXCLUDE_FROM_ALL')
        self._write('    {}/dummy.cc'.format(GENERATED))
        for source in sources:
            self._write('    {}'.format(source))
        self._write(')\n')

    def custom_target(self, unqualified_name, sources, dependencies):
        self._write('add_custom_target(')
        self._write('    {}'.format(unqualified_name))
        if len(dependencies) or len(sources):
            self._write('    DEPENDS')
        for dependency in dependencies:
            self._write('    {}'.format(dependency))
        for source in sources:
            self._write('    {}'.format(source))
        self._write(')\n')

    def object_library(self, unqualified_name, category, sources):
        self._write('add_library(')
        self._write('    {}-{} OBJECT'.format(unqualified_name, category))
        self._write('    EXCLUDE_FROM_ALL')
        for source in sorted(sources):
            self._write('    {}'.format(source))
        self._write(')\n')

    def interface_library(self, unqualified_name):
        self._write('add_library(')
        self._write('    {} INTERFACE'.format(unqualified_name))
        self._write(')\n')
        self._interfaces.add(unqualified_name)

    def target(self, target_type, lib_type, unqualified_name, source_categories):
        self._write('add_{}('.format(target_type))
        self._write('    {}'.format(unqualified_name))
        self._write('    EXCLUDE_FROM_ALL')
        for category in source_categories:
            self._write('    $<TARGET_OBJECTS:{}-{}>'.format(unqualified_name,
                category))
        self._write(')\n')

    def generated_sources(self, sources):
        self._write('set_source_files_properties(')
        for source in sources:
            self._write('    {}'.format(source))
        self._write('    PROPERTIES GENERATED TRUE')
        self._write(')')

def unqualify_name(gyp_target):
    return gyp_target.split(':')[1].split('#')[0]

def get_sources_flags_by_category(target, sources):
    result = defaultdict(lambda: [set(), None])
    for source in sources:
        extension = os.path.splitext(source)[1]
        if extension in SOURCE_CATEGORIES:
            result[SOURCE_CATEGORIES[extension]][0].add(source)
    flags_factories = get_flags_factories(target)
    for category in SOURCE_CATEGORIES.itervalues():
        result[category][1] = flags_factories(category)

    return { category: value for category, value in result.iteritems() \
                                                             if len(value[0]) }

def generate_config_properties(writer,
                               target_name,
                               target,
                               get_properties,
                               cmake_name,
                               reorderable=False):
    general_properties  = list(get_properties(None, target))
    specific_properties = {
        name: list(get_properties(name, target['configurations'][name])) \
                                           for name in CONFIGURATIONS    \
                                           if name in target['configurations']
    }

    flattened_properties = {
        name: general_properties + properties \
                        for name, properties in specific_properties.iteritems()
    }

    if reorderable:
        common_properties = [set(properties) for properties in flattened_properties.itervalues()]
        common_properties = reduce(set.intersection, common_properties)
        writer.properties(cmake_name, target_name, common_properties)
        for configuration_name, properties in specific_properties.iteritems():
            properties = set(properties) - common_properties
            writer.configuration_properties(cmake_name,
                                            target_name,
                                            configuration_name,
                                            properties)
    else:
        all_properties = flattened_properties.itervalues()
        first_properties = next(all_properties)
        if all([first_properties == properties for properties in all_properties]):
            writer.properties(cmake_name, target_name, first_properties)
        else:
            writer.properties(cmake_name, target_name, general_properties)
            for configuration_name, properties in sorted(specific_properties.iteritems()):
                writer.configuration_properties(cmake_name,
                                                target_name,
                                                configuration_name,
                                                properties)

def generate_target(platform, name, target, working_directory, analysis):
    unqualified_name = unqualify_name(name)
    path             = os.path.dirname(os.path.relpath(name.split(':')[0],
                                                       working_directory))

    lists = os.path.join(path, 'CMakeLists.txt')
    cmake = os.path.join(path, '{}.cmake'.format(unqualified_name))

    with open(lists, 'a') as f:
        print('include({})'.format(os.path.basename(cmake)), file=f)

    with open(cmake, 'a') as f:
        writer = Writer(f)
        writer.platform_start(platform)
        sources = set(target['sources'])
        for action in target.get('actions', []):
            writer.custom_command(action['inputs'],
                                  action['action'],
                                  action['outputs'])
            sources |= set(action['outputs'])

        dependencies  = []
        dependencies += target.get('dependencies', [])
        dependencies += target.get('dependencies_original', [])

        link_dependencies    = set()
        nonlink_dependencies = set()
        all_dependencies     = set()
        for d in dependencies:
            unqualified_depedency = unqualify_name(d)

            all_dependencies.add(unqualified_depedency)

            if d in analysis['executables']:
                continue

            if d in analysis['interface_libraries']:
                nonlink_dependencies.add(unqualified_depedency)
            else:
                link_dependencies.add(unqualified_depedency)

        target_type = None
        library_type = None
        if target['type'] == 'static_library':
            target_type = 'library'
            library_type = 'STATIC'
        elif target['type'] == 'shared_library':
            target_type = 'library'
            library_type = 'SHARED'
        elif target['type'] == 'executable':
            target_type = 'executable'

        if name in analysis['generated_libraries']:
            writer.library_with_actions(unqualified_name, sources)
        elif name in analysis['interface_libraries']:
            if len(sources) == 0:
                # TBD: do we need to export 'c' flags also?
                flags_factory = get_flags_factories(target)('cc')

                writer.interface_library(unqualified_name)
                generate_config_properties(writer,
                                           unqualified_name,
                                           target,
                                           flags_factory,
                                           'target_compile_options')
                generate_config_properties(writer,
                                           unqualified_name,
                                           target,
                                           lambda _, target: target.get('include_dirs', []),
                                           'target_include_directories')
                generate_config_properties(writer,
                                           unqualified_name,
                                           target,
                                           lambda _, target: target.get('defines', []),
                                           'target_compile_definitions',
                                           True)
            else:
                writer.custom_target(unqualified_name, sources, all_dependencies)

            generate_config_properties(writer,
                                       unqualified_name,
                                       target,
                                       lambda _, target: link_dependencies,
                                       'target_link_libraries',
                                       True)
        elif target_type:
            sources_flags_by_category = get_sources_flags_by_category(target, sources)
            for category, sources_flags in sources_flags_by_category.iteritems():
                sources, flags = sources_flags
                if len(sources) == 0:
                    continue

                writer.object_library(unqualified_name, category, sources)
                generate_config_properties(writer,
                                           '{}-{}'.format(unqualified_name, category),
                                           target,
                                           flags,
                                           'target_compile_options')
                generate_config_properties(writer,
                                           '{}-{}'.format(unqualified_name, category),
                                           target,
                                           lambda _, target: target.get('include_dirs', []),
                                           'target_include_directories')
                generate_config_properties(writer,
                                           '{}-{}'.format(unqualified_name, category),
                                           target,
                                           lambda _, target: target.get('defines', []),
                                           'target_compile_definitions',
                                           True)

                generated_sources = [s for s in sources if s in analysis['all_generated_sources']]
                if len(generated_sources) > 0:
                    writer.generated_sources(generated_sources)

                writer.properties('add_dependencies',
                                  '{}-{}'.format(unqualified_name, category),
                                  nonlink_dependencies)

            writer.target(target_type,
                          library_type,
                          unqualified_name,
                          sources_flags_by_category.keys())

            generate_config_properties(writer,
                                       unqualified_name,
                                       target,
                                       lambda _, target: list(link_dependencies) + target.get('libraries', []) + target.get('ldflags', []),
                                       'target_link_libraries',
                                       True)
        writer.platform_end()

    return lists, unqualified_name

def analyze(targets):
    executables           = set()
    generated_libraries   = set()
    interface_libraries   = set()
    all_generated_sources = set()

    for name, target in targets.iteritems():
        if target['type'] == 'executable':
            executables.add(name)
        if 'sources' not in target:
            produces_sources = False
            for action in target.get('actions', []):
                if action.get('process_outputs_as_sources', False):
                    produces_sources = True
                for output in action.get('outputs', []):
                    if output.startswith('${CMAKE_BINARY_DIR}/generated_%%ncg_guid%%'):
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

def generate_target_cmakes(platform, names, targets, data, params):
    analysis = analyze(targets)
    all_lists = defaultdict(set)
    for name, target in targets.iteritems():
        if target['type'] not in KNOWN_TARGET_TYPES:
            raise RuntimeError('Unknown target type: {}'.format(target['type']))

        target['sources'] = target.get('sources', [])
        target['actions'] = target.get('actions', [])

        lists, unqualified_name = generate_target(platform,
                                                  name,
                                                  target,
                                                  params['cwd'],
                                                  analysis)
        if unqualified_name in all_lists[lists]:
            raise RuntimeError(
                  'Multiple targets with the same name: {} in {}'.format(lists,
                                                                         unqualified_name))
        all_lists[lists].add(unqualified_name)

    with open('CMakeLists.txt', 'w') as f:
        print('cmake_minimum_required(VERSION 3.8)\n', file=f)
        print('file(WRITE {}/dummy.cc "")\n'.format(GENERATED), file=f)
        for lists, targets in all_lists.iteritems():
            directory = os.path.dirname(lists)
            if directory == '':
                for target in targets:
                    print('include({}.cmake)'.format(target), file=f)
            else:
                print('add_subdirectory({})'.format(directory), file=f)

def main():
    with open(ANALYSIS_FILE, 'r') as f:
        all_platforms = json.load(f)
        for platform, data in all_platforms.iteritems():
            generate_target_cmakes(get_CMake_OS(platform),
                                   data['names'],
                                   data['targets'],
                                   data['data'],
                                   data['params'])

if __name__ == '__main__':
    main()
