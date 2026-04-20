# Introduction

Simple python script that generates compile_commands.json file (used by many tools) starting from several sources.

Actually only Atmel Studio projects file is implemented as source.

# Usage

```
usage: gen_compile_commands.py [-h] [--cproj CPROJ] [--build-conf BUILD_CONF] [--compiler COMPILER] [-o OUTPUT]

Generate compile_commands.json from an Atmel Studio .cproj file.

options:
  -h, --help            show this help message and exit
  --cproj CPROJ         Path to the .cproj file. Auto-detected if omitted.
  --build-conf BUILD_CONF
                        Build configuration name (e.g. Debug, Release). Optional if only one configuration exists in
                        the project.
  --compiler COMPILER   Compiler executable (default: arm-none-eabi-gcc)
  -o, --output OUTPUT   Output file path (default: compile_commands.json in project dir)
```


