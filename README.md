# NodeJS CMake Generator

This repository contains Python scripts that produce modern CMake for the
NodeJS project from its GYP files.  It has been tested for Node 12 on macOS and
Linux platforms, though it may work on other platforms.

## Why Not Use GYP's CMake support?

The original motivation for this project was to incorporate NodeJS as a library
in an external CMake project.  While GYP supports generating CMake output, the
generated files make certain assumptions about how CMake will be used that did
not fit the requirements of this external project.

Instead, the generator in this repo makes fewer assumptions.  This likely comes
at a cost of incomplete support of all of GYP's capabilities, but is enough to
build NodeJS which was the goal.

## Requirements

 * Python 2 (needed by GYP)
 * CMake
 * C++ Toolchain (Xcode/Command Line Tools, GCC, Visual Studio, etc.)

## Instructions

The following instructions are for macOS, adapt to your platform as needed.

```bash
# clone this repo
$ git clone https://github.com/frutiger/ncg

# clone NodeJS and change directory into it
$ git clone https://github.com/nodejs/node && cd node

# checkout v12 branch
$ git checkout v12.x

# apply patches to fix erroneous deps/v8/BUILD.gn
$ git am ../ncg/patch/*

# delete any existing CMake files, these will interfere with our generated
# files
$ git ls-files "**.cmake" "**/CMakeLists.txt" | xargs rm

# run GYP using our custom generator on all relevant platforms
# this produces a gyp_analysis.json file which we will use in the next step
$ ./configure --download=all --shared --with-intl=full-icu \
              --openssl-no-asm --without-dtrace --without-snapshot \
              -- -f ../ncg/analyse.py

# generate CMake files
# NOTE: this needs to be run with Python 2
$ PYTHONPATH=tools/gyp/pylib python ../ncg/generate.py

# macOS only: remove CoreFoundation frameworks from link lines, as this
# confuses CMake
$ sed -i '' '/CoreFoundation/d' node.cmake node_mksnapshot.cmake \
                                libnode.cmake cctest.cmake mkcodecache.cmake

# generate Ninja files
$ cd ..
$ mkdir out && cd out
$ cmake -D CMAKE_BUILD_TYPE=Release -D CMAKE_CXX_STANDARD=14 -G Ninja ../node

# build all targets
$ ninja
```

## How it works

`analyse.py` specifies the current OS as the target OS, a randomly generated
path as the shared intermediate directory, and then takes the fully expanded
output from GYP and appends the information to a file.

`generate.py` reads this serialized file and creates a `<target_name>.cmake`
file for each target in the same directory as the GYP file.  It creates
`executable`, `shared_library` or `static_library` targets as needed with their
respective source files, include directories, compiler flags etc.

This two-step process allows the analysis step to run on multiple platforms
allowing the generation step to produce a single set of CMake files that work
on multiple platforms.

## Future Work

We plan to maintain this change for newer versions of NodeJS (e.g. Node 13).

The generated CMake includes a block for each combination of _configuration_
(e.g. `Debug` vs. `Release`) and each operating system.  Finding commonalities
could reduce the amount of generated CMake.

This generator was crafted to produce modern CMake for NodeJS.  While it may
work on other GYP projects, it has not exhaustively been tested for everything
GYP can support.

It is not tenable for NodeJS to maintain GYP files for upstream V8 (which no
longer uses GYP) nor for its other dependencies.  The one-time output of this
project can be used to move to CMake which can be manually maintained going
forwards.  The CMake required to build a Node Add-On is also minimal and does
not need the full GYP machinery (the headers and a few linker options are all
that is needed).

