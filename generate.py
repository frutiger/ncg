from __future__ import print_function

import os
import json

from collections import defaultdict

import gyp.xcode_emulation
import gyp.msvs_emulation

ANALYSIS_FILE = 'gyp_analysis.json'

CONFIGURATIONS = {'Debug', 'Release'}
KNOWN_TARGET_TYPES = {'shared_library', 'static_library', 'executable', 'none'}
SOURCE_CATEGORIES = {
    'c':  {'.c'},
    'cc': {'.cc', '.cpp', '.cxx'},
}
GENERATED = '${CMAKE_BINARY_DIR}/ncg_generated'

def get_cmake_os(platform):
    if platform.startswith('linux'):
        return 'Linux'

    if platform == 'win32':
        return 'Windows'

    if platform == 'darwin':
        return 'Darwin'

    raise RuntimeError('Unknown platform: {}'.format(platform))

class Properties(object):
    def __init__(self, category):
        self._category = category

    def compile_flags(self, configuration_name, configuration):
        if configuration_name is None:
            return []

        flags = []
        if self._category == 'c':
            flags += configuration.get('cflags_c', [])
        elif self._category == 'cc':
            flags += configuration.get('cflags_cc', [])
        else:
            raise RuntimeError('Unknown category: ' + self._category)
        flags += configuration.get('cflags', [])

        return flags

    @staticmethod
    def defines(self, configuration_name, configuration):
        return configuration.get('defines', [])

    @staticmethod
    def include_dirs(self, configuration_name, configuration):
        return configuration.get('include_dirs', [])

class EmulatedProperties(object):
    def __init__(self, settings, category):
        self._settings = settings
        self._category = category

    def compile_flags(self, configuration_name, configuration):
        if configuration_name is None:
            return []

        flags = []
        if self._category == 'c':
            flags += self._settings.GetCflagsC(configuration_name)
        elif self._category == 'cc':
            flags += self._settings.GetCflagsCC(configuration_name)
        else:
            raise RuntimeError('Unknown category: ' + self._category)
        flags += self._settings.GetCflags(configuration_name)

        return flags

    def defines(self, configuration_name, configuration):
        defines = Properties.defines(configuration_name, configuration)

        if hasattr(self._settings, 'GetComputedDefines'):
            defines += self._settings.GetComputedDefines(configuration_name)

        return defines

    def include_dirs(self, configuration_name, configuration):
        return Properties.include_dirs(configuration_name, configuration)

def get_properties_factory(platform, target, category):
    if platform == 'Darwin':
        return EmulatedProperties(gyp.xcode_emulation.XcodeSettings(target),
                                  category)
    elif platform == 'Windows':
        return EmulatedProperties(gyp.msvs_emulation.MsvsSettings(target, {}),
                                  category)
    else:
        return Properties(category)

class Writer(object):
    def __init__(self, file):
        self._file         = file
        self._interfaces   = set()
        self._indent_level = 0

    def _write(self, *args, **kwargs):
        indentation = ''.join(' ' for i in range(self._indent_level))
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
        if lib_type:
            self._write('    {} {}'.format(unqualified_name, lib_type))
        else:
            self._write('    {}'.format(unqualified_name))
        for category in source_categories:
            self._write('    $<TARGET_OBJECTS:{}-{}>'.format(unqualified_name,
                category))
        self._write(')\n')

    def generated_sources(self, sources):
        self._write('set_source_files_properties(')
        for source in sources:
            self._write('    {}'.format(source))
        self._write('    PROPERTIES GENERATED TRUE')
        self._write(')\n')

    def copies(self, destination, files):
        self._write('file(')
        self._write('    COPY')
        for file in files:
            self._write('    {}'.format(file))
        self._write('    DESTINATION {}'.format(destination))
        self._write(')\n')

def unqualify_name(gyp_target):
    return gyp_target.split(':')[1].split('#')[0]

def get_sources_properties_by_category(platform, target, sources):
    result = defaultdict(lambda: [set(), None])

    for source in sources:
        extension = os.path.splitext(source)[1]
        for category, extensions in SOURCE_CATEGORIES.iteritems():
            if extension in extensions:
                result[category][0].add(source)
    for category in SOURCE_CATEGORIES:
        if len(result[category][0]):
            for source in sources:
                extension = os.path.splitext(source)[1]
                if extension == '.h':
                    result[category][0].add(source)
    for category in SOURCE_CATEGORIES:
        result[category][1] = get_properties_factory(platform, target, category)

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

def generate_target(platform, name, target, analysis, all_targets):
    unqualified_name = unqualify_name(name)
    path             = os.path.dirname(name.split(':')[0])

    lists = os.path.join(path, 'CMakeLists.txt')
    cmake = os.path.join(path, '{}.cmake'.format(unqualified_name))

    if unqualified_name not in all_targets:
        all_targets.add(unqualified_name)
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

        link_dependencies    = []
        nonlink_dependencies = []
        all_dependencies     = []
        for d in dependencies:
            unqualified_depedency = unqualify_name(d)

            all_dependencies.append(unqualified_depedency)

            if d in analysis['generated_libraries'] or \
                                                  d in analysis['executables']:
                nonlink_dependencies.append(unqualified_depedency)
            else:
                link_dependencies.append(unqualified_depedency)

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
            writer.custom_target(unqualified_name, sources, [])
        elif name in analysis['interface_libraries']:
            if len(sources) > 0:
                action_target = '{}-{}'.format(unqualified_name, 'actions')
                writer.custom_target(action_target, sources, all_dependencies)
                nonlink_dependencies.append(action_target)

            # TBD: do we need to export 'c' flags also?
            properties = get_properties_factory(platform, target, 'cc')

            writer.interface_library(unqualified_name)
            generate_config_properties(writer,
                                       unqualified_name,
                                       target,
                                       properties.compile_flags,
                                       'target_compile_options')
            generate_config_properties(writer,
                                       unqualified_name,
                                       target,
                                       properties.include_dirs,
                                       'target_include_directories')
            generate_config_properties(writer,
                                       unqualified_name,
                                       target,
                                       properties.defines,
                                       'target_compile_definitions',
                                       True)
            generate_config_properties(writer,
                                       unqualified_name,
                                       target,
                                       lambda _, target: link_dependencies,
                                       'target_link_libraries')

            writer.properties('add_dependencies', unqualified_name, nonlink_dependencies)
        elif target_type:
            sources_properties_by_category = get_sources_properties_by_category(platform, target, sources)
            for category, sources_properties in sources_properties_by_category.iteritems():
                sources, properties = sources_properties
                if len(sources) == 0:
                    continue

                writer.object_library(unqualified_name, category, sources)
                generate_config_properties(writer,
                                           '{}-{}'.format(unqualified_name, category),
                                           target,
                                           properties.compile_flags,
                                           'target_compile_options')
                generate_config_properties(writer,
                                           '{}-{}'.format(unqualified_name, category),
                                           target,
                                           properties.include_dirs,
                                           'target_include_directories')
                generate_config_properties(writer,
                                           '{}-{}'.format(unqualified_name, category),
                                           target,
                                           properties.defines,
                                           'target_compile_definitions',
                                           True)

                generated_sources = [s for s in sources if s in analysis['all_generated_sources']]
                if len(generated_sources) > 0:
                    writer.generated_sources(generated_sources)

                writer.properties('add_dependencies',
                                  '{}-{}'.format(unqualified_name, category),
                                  nonlink_dependencies)

            for copy in target.get('copies', []):
                writer.copies(copy['destination'], copy['files'])

            writer.target(target_type,
                          library_type,
                          unqualified_name,
                          sources_properties_by_category.keys())

            generate_config_properties(writer,
                                       unqualified_name,
                                       target,
                                       lambda _, target: link_dependencies + target.get('libraries', []) + target.get('ldflags', []),
                                       'target_link_libraries')
        writer.platform_end()

    return lists, unqualified_name

def generate_target_cmakes(platform, targets, analysis, all_targets):
    all_lists   = defaultdict(set)
    for name, target in targets.iteritems():
        if target['type'] not in KNOWN_TARGET_TYPES:
            raise RuntimeError('Unknown target type: {}'.format(target['type']))

        target['sources'] = target.get('sources', [])
        target['actions'] = target.get('actions', [])

        lists, unqualified_name = generate_target(platform,
                                                  name,
                                                  target,
                                                  analysis,
                                                  all_targets)
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
        all_targets = set()
        for platform, data in all_platforms.iteritems():
            cmake_os = get_cmake_os(platform)
            print('Writing files for platform: {}'.format(cmake_os))
            generate_target_cmakes(cmake_os,
                                   data['targets'],
                                   data['analysis'],
                                   all_targets)

if __name__ == '__main__':
    main()

