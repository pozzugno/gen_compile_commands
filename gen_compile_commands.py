#!/usr/bin/env python3
"""Generate compile_commands.json from an Atmel Studio .cproj file."""

import argparse
import glob
import json
import os
import re
import sys
import xml.etree.ElementTree as ET


NS = "http://schemas.microsoft.com/developer/msbuild/2003"


def find_cproj_files(search_dir):
    return glob.glob(os.path.join(search_dir, "*.cproj"))


def parse_cproj(cproj_path):
    tree = ET.parse(cproj_path)
    root = tree.getroot()
    return root


def strip_ns(tag):
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def find_elements(parent, tag_name):
    results = []
    for elem in parent.iter():
        if strip_ns(elem.tag) == tag_name:
            results.append(elem)
    return results


def get_text(elem):
    if elem is not None and elem.text:
        return elem.text.strip()
    return None


def get_list_values(parent, tag_name):
    values = []
    for elem in find_elements(parent, tag_name):
        if strip_ns(elem.tag) == tag_name:
            for lv in find_elements(elem, "ListValues"):
                for v in find_elements(lv, "Value"):
                    t = get_text(v)
                    if t:
                        values.append(t)
    return values


def detect_configurations(root):
    configs = []
    for pg in find_elements(root, "PropertyGroup"):
        condition = pg.get("Condition", "")
        m = re.search(r"'\$\(Configuration\)'\s*==\s*'([^']*)'", condition)
        if m:
            configs.append(m.group(1))
    return configs


def get_output_directory(root, project_dir, config_name):
    for elem in find_elements(root, "OutputDirectory"):
        t = get_text(elem)
        if t:
            t = t.replace("$(MSBuildProjectDirectory)", project_dir)
            t = t.replace("$(Configuration)", config_name)
            name_elem = None
            for n in find_elements(root, "Name"):
                nt = get_text(n)
                if nt:
                    name_elem = nt
                    break
            if name_elem:
                t = t.replace("$(MSBuildProjectName)", name_elem)
            return os.path.normpath(t)
    return os.path.join(project_dir, config_name)


def get_toolchain_settings(root, config_name):
    for pg in find_elements(root, "PropertyGroup"):
        condition = pg.get("Condition", "")
        m = re.search(r"'\$\(Configuration\)'\s*==\s*'([^']*)'", condition)
        if m and m.group(1) == config_name:
            for ts in find_elements(pg, "ToolchainSettings"):
                for arm in find_elements(ts, "ArmGcc"):
                    return arm
    return None


def parse_optimization_level(armgcc):
    for elem in find_elements(armgcc, "armgcc.compiler.optimization.level"):
        t = get_text(elem)
        if t:
            m = re.search(r"\((-O\S+)\)", t)
            if m:
                return m.group(1)
    return ""


def parse_debug_level(armgcc):
    for elem in find_elements(armgcc, "armgcc.compiler.optimization.DebugLevel"):
        t = get_text(elem)
        if t:
            m = re.search(r"\((-g\S*)\)", t)
            if m:
                return m.group(1)
    return ""


def parse_other_flags(armgcc):
    for elem in find_elements(armgcc, "armgcc.compiler.miscellaneous.OtherFlags"):
        t = get_text(elem)
        if t:
            return t
    return ""


def get_device_info(root):
    series = ""
    for elem in find_elements(root, "avrdeviceseries"):
        t = get_text(elem)
        if t:
            series = t.lower()
            break
    toolchain = ""
    for elem in find_elements(root, "ToolchainName"):
        t = get_text(elem)
        if t:
            toolchain = t.lower()
            break
    device = ""
    for elem in find_elements(root, "avrdevice"):
        t = get_text(elem)
        if t:
            device = t
            break
    return toolchain, series, device


def infer_cpu_flags(toolchain, series):
    if "arm" in toolchain:
        if "samc2" in series:
            return ["-mcpu=cortex-m0plus", "-mthumb"]
        elif "same5" in series or "same5" in series:
            return ["-mcpu=cortex-m4", "-mthumb"]
        elif "sams" in series or "sama" in series:
            return ["-mcpu=cortex-m7", "-mthumb"]
        else:
            return ["-mthumb"]
    return []


def collect_compile_sources(root, project_dir):
    sources = []
    for ig in find_elements(root, "ItemGroup"):
        for compile_elem in find_elements(ig, "Compile"):
            inc = compile_elem.get("Include", "")
            if inc and inc.endswith(".c"):
                abs_path = os.path.normpath(os.path.join(project_dir, inc.replace("/", os.sep)))
                if os.path.isfile(abs_path):
                    sources.append(abs_path)
    return sorted(set(sources))


def resolve_include_paths(include_values, output_dir):
    resolved = []
    for p in include_values:
        abs_path = os.path.normpath(os.path.join(output_dir, p.replace("/", os.sep)))
        resolved.append(abs_path)
    return resolved


def build_command(compiler, opt, dbg, other_flags, cpu_flags, defines, includes, source):
    parts = [compiler]
    if opt:
        parts.append(opt)
    if dbg:
        parts.append(dbg)
    parts.extend(cpu_flags)
    if other_flags:
        parts.append(other_flags)
    for d in defines:
        parts.append("-D" + d)
    for i in includes:
        parts.append("-I" + i)
    parts.append("-c")
    parts.append(source)
    return " ".join(parts)


def to_forward_slash(p):
    return p.replace("\\", "/")


def main():
    parser = argparse.ArgumentParser(
        description="Generate compile_commands.json from an Atmel Studio .cproj file."
    )
    parser.add_argument("--cproj", help="Path to the .cproj file. Auto-detected if omitted.")
    parser.add_argument("--build-conf", help="Build configuration name (e.g. Debug, Release). "
                        "Optional if only one configuration exists in the project.")
    parser.add_argument("--compiler", default="arm-none-eabi-gcc",
                        help="Compiler executable (default: arm-none-eabi-gcc)")
    parser.add_argument("-o", "--output", default=None,
                        help="Output file path (default: compile_commands.json in project dir)")
    args = parser.parse_args()

    # Resolve .cproj path
    cproj_path = args.cproj
    if not cproj_path:
        found = find_cproj_files('.')
        if len(found) == 0:
            print(f"Error: no .cproj files found in the current directory", file=sys.stderr)
            print("Use --cproj to specify the path.", file=sys.stderr)
            sys.exit(1)
        elif len(found) > 1:
            print(f"Error: multiple .cproj files found in the current directory:", file=sys.stderr)
            for f in found:
                print(f"  {os.path.basename(f)}", file=sys.stderr)
            print("Use --cproj to specify which one to use.", file=sys.stderr)
            sys.exit(1)
        cproj_path = found[0]

    cproj_path = os.path.abspath(cproj_path)
    project_dir = os.path.dirname(cproj_path)

    if not os.path.isfile(cproj_path):
        print(f"Error: file not found: {cproj_path}", file=sys.stderr)
        sys.exit(1)

    root = parse_cproj(cproj_path)

    # Detect configurations
    configs = detect_configurations(root)
    if not configs:
        print("Error: no build configurations found in .cproj file.", file=sys.stderr)
        sys.exit(1)

    config_name = args.build_conf
    if not config_name:
        if len(configs) == 1:
            config_name = configs[0]
        else:
            print(f"Error: multiple build configurations found: {', '.join(configs)}", file=sys.stderr)
            print("Use --build-conf to specify which one to use.", file=sys.stderr)
            sys.exit(1)
    elif config_name not in configs:
        print(f"Error: configuration '{config_name}' not found.", file=sys.stderr)
        print(f"Available configurations: {', '.join(configs)}", file=sys.stderr)
        sys.exit(1)

    # Get output directory
    output_dir = get_output_directory(root, project_dir, config_name)

    # Get toolchain settings
    armgcc = get_toolchain_settings(root, config_name)
    if armgcc is None:
        print(f"Error: no ArmGcc toolchain settings found for configuration '{config_name}'.",
              file=sys.stderr)
        sys.exit(1)

    # Extract settings
    defines = get_list_values(armgcc, "armgcc.compiler.symbols.DefSymbols")
    include_values = get_list_values(armgcc, "armgcc.compiler.directories.IncludePaths")
    includes = resolve_include_paths(include_values, output_dir)
    opt = parse_optimization_level(armgcc)
    dbg = parse_debug_level(armgcc)
    other_flags = parse_other_flags(armgcc)
    toolchain, series, device = get_device_info(root)
    cpu_flags = infer_cpu_flags(toolchain, series)

    # Inject the device-specific macro that Atmel Studio auto-defines
    if device:
        bare_device = device.upper()
        if bare_device.startswith("AT"):
            bare_device = bare_device[2:]
        device_macro = "__" + bare_device + "__"
        if device_macro not in defines:
            defines.insert(0, device_macro)
        device_macro_at = "__AT" + bare_device + "__"
        if device_macro_at not in defines:
            defines.insert(0, device_macro_at)

    # Collect source files
    sources = collect_compile_sources(root, project_dir)
    if not sources:
        print("Warning: no .c source files found.", file=sys.stderr)

    # Build compile_commands.json
    entries = []
    for src in sources:
        cmd = build_command(
            args.compiler, opt, dbg, other_flags, cpu_flags,
            defines, includes, to_forward_slash(src)
        )
        entries.append({
            "directory": to_forward_slash(project_dir),
            "command": cmd,
            "file": to_forward_slash(src),
        })

    # Write output
    output_path = args.output
    if not output_path:
        output_path = os.path.join(project_dir, "compile_commands.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)

    print(f"Generated {output_path} with {len(entries)} entries "
          f"(configuration: {config_name})")


if __name__ == "__main__":
    main()
