#!/usr/bin/env python3
"""Generate performance_check_notebook.md for stress-testing Neptune."""
import os

def generate(output_path: str):
    lines = []
    lines.append("# Neptune Performance Check Notebook")
    lines.append("")
    lines.append("Generated stress test with 100+ blocks to evaluate scroll,")
    lines.append("render, PTY throughput, and lazy-load performance.")
    lines.append("")
    lines.append("## How to use")
    lines.append("1. Start Neptune: `python3 main.py all --clean-history -s test.sock`")
    lines.append("2. Import this notebook: `:import scripts/performance_check_notebook.md`")
    lines.append("3. Scroll through all blocks using `j`/`k`")
    lines.append("4. Enter CONTROL mode on running blocks")
    lines.append("5. Watch for lag, freezes, or visual glitches")
    lines.append("6. Time how long each section takes to render")
    lines.append("")

    # ────────────────────── Section 1: Smoke (blocks 1-5) ──────────────────────
    lines.append("## Section 1: Smoke Tests")
    lines.append("Basic blocks to verify import & display work.")
    lines.append("")
    for i in range(1, 6):
        lines.append(f"### Smoke Note {i}")
        lines.append(f"This is smoke test note block #{i}.")
        lines.append(f"Lorem ipsum dolor sit amet, consectetur adipiscing elit. ")
        lines.append(f"Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. " * 2)
        lines.append("")

    lines.append(generate_cmd_block(
        "echo '=== SMOKE OK ===' && date && whoami && pwd",
        generate_large_output("SMOKE OK", 10)
    ))
    lines.append("")

    # ────────────────────── Section 2: Medium Heave (blocks 6-25) ──────────────────────
    lines.append("## Section 2: Medium Load")
    lines.append("20 blocks with moderate output to test scroll + render.")
    lines.append("")
    for i in range(6, 26):
        lines.append(f"### Note Block {i}")
        lines.append(f"Medium load note for block {i}. " * 4)
        lines.append("")
        cmd = f"echo 'Block {i} output'; seq 1 30 | while read n; do echo 'Line $n of output for block {i}'; done"
        lines.append(generate_cmd_block(cmd, generate_large_output(f"Block {i} output", 30)))
        lines.append("")

    # ────────────────────── Section 3: Heavy Output (blocks 26-45) ──────────────────────
    lines.append("## Section 3: Heavy Output Stress")
    lines.append("Commands with large output to test PTY throughput + debounce.")
    lines.append("")
    heavy_commands = [
        ("find /usr -type f 2>/dev/null | head -200", generate_large_output_from_list([f"/usr/share/file{i}.ext" for i in range(200)])),
        ("ls -laR /usr/share/doc 2>/dev/null | head -300", generate_large_output_from_list([f"-rw-r--r-- 1 root root {i*100} Jan 1 12:00 doc_{i}.txt" for i in range(300)])),
        ("ps aux --sort=-%mem | head -100", generate_large_output_from_list([f"root   {i}  0.1  0.2  {i*100} {i*50} ? Ss 12:00 0:00 /usr/bin/proc_{i}" for i in range(100)])),
        ("dmesg 2>/dev/null | tail -200", generate_large_output_from_list([f"[{i}.{i*100}] kernel: device {i} initialized" for i in range(200)])),
        ("journalctl -xe 2>/dev/null | tail -250", generate_large_output_from_list([f"Jun 24 12:00:{i:02d} host systemd[{i}]: Service {i} started successfully" for i in range(250)])),
        ("cat /proc/cpuinfo | head -200", generate_large_output_from_list([f"processor{i} : ARMv{i} Processor rev {i}" for i in range(50)] + [f"cpu MHz  : {i*100}.0{i}" for i in range(50)] + [f"BogoMIPS : {i*10}.00" for i in range(50)])),
        ("df -h; echo '---'; free -h; echo '---'; ip a 2>/dev/null | head -100", generate_large_output_from_list(["/dev/sda1  100G  50G  50G  50%  /", "Mem:  16G  8G  8G", "1: lo: <LOOPBACK> mtu 65536"] * 30)),
        ("pip list 2>/dev/null || apt list --installed 2>/dev/null | head -200", generate_large_output_from_list([f"package-{i}-v{i}.0.0" for i in range(200)])),
        ("compgen -c 2>/dev/null | head -200 || ls /usr/bin | head -200", generate_large_output_from_list([f"command_{i}" for i in range(200)])),
        ("tree -L 3 /usr 2>/dev/null | head -300", generate_large_output_from_list([f"{'│ ' * (i % 4)}{'├── ' if i % 2 else '└── '}dir_{i}" for i in range(300)])),
        ("find /etc -type f -name '*.conf' 2>/dev/null | head -200", generate_large_output_from_list([f"/etc/{'dir' + str(i % 20)}/config_{i}.conf" for i in range(200)])),
        ("sysctl -a 2>/dev/null | head -250", generate_large_output_from_list([f"net.core.{'param' + str(i)} = {i}" for i in range(250)])),
        ("systemctl list-units --type=service --all 2>/dev/null | head -250", generate_large_output_from_list([f"service_{i}.service  loaded  active  {'running' if i % 2 else 'exited'}  Service {i} Description" for i in range(250)])),
        ("perl -e 'for(1..150){print \"Line $_ \", \"x\" x 80, \"\\n\"}'", generate_large_output_from_list([f"Line {i} " + "x" * 80 for i in range(150)])),
        ("python3 -c 'import this'", generate_large_output_from_list(["The Zen of Python, by Tim Peters", "Beautiful is better than ugly.", "Explicit is better than implicit."] * 40)),
        ("od -An -tx1 /dev/urandom | head -200 2>/dev/null", generate_large_output_from_list([f"{' '.join(f'{b:02x}' for b in range(i % 16, i % 16 + 16))}" for i in range(200)])),
        ("grep -r '^\s*#' /etc/ 2>/dev/null | head -200", generate_large_output_from_list([f"/etc/config{i}.conf:# This is configuration option {i}" for i in range(200)])),
        ("lsof 2>/dev/null | head -200 || echo 'lsof not available'", generate_large_output_from_list([f"process_{i}  {i}  root  {i}u  REG  8,1  {i*100}  {i}  /var/log/file_{i}.log" for i in range(200)])),
        ("nm -D /lib/x86_64-linux-gnu/libc.so.6 2>/dev/null | head -200", generate_large_output_from_list([f"{i:08x} T function_{i}" for i in range(200)])),
        ("echo '=== Heavy Command 20 Done ==='", generate_large_output("=== Heavy Command 20 Done ===", 1)),
    ]
    for i, (cmd, output) in enumerate(heavy_commands, start=26):
        lines.append(f"### Heavy Command {i}")
        lines.append(f"Stress test #{i+1}: heavy output, long lines, special chars.")
        lines.append("")
        lines.append(generate_cmd_block(cmd, output))
        lines.append("")

    # ────────────────────── Section 4: Multi-PTY (blocks 46-55) ──────────────────────
    lines.append("## Section 4: Multi-PTY Stress")
    lines.append("Commands on PTY uid:1 to test multi-PTY performance.")
    lines.append("")
    for i in range(46, 56):
        cmd = f"echo 'PTY1 block {i}'; seq 1 20 | while read n; do echo 'Pty1 line $n block {i}'; done"
        lines.append(generate_cmd_block(cmd, generate_large_output(f"PTY1 block {i}", 20), uid=1))
        lines.append(f"### Note Block {i}")
        lines.append(f"Interleaved note for multi-pty block {i}. " * 3)
        lines.append("")

    # ────────────────────── Section 5: Memory Pressure (blocks 56-75) ──────────────────────
    lines.append("## Section 5: Memory Pressure")
    lines.append("Blocks with large text to stress memory + output buffer.")
    lines.append("")
    for i in range(56, 76):
        lines.append(f"### Large Note {i}")
        lines.append(f"Long text block #{i}. " * 30)
        lines.append("")
        long_cmd = f"echo 'Long command {i}'; for n in $(seq 1 40); do echo 'Long line $n of command {i} with lots of extra text to make each line heavier'; done"
        lines.append(generate_cmd_block(long_cmd, generate_large_output(f"Long command {i}", 40)))
        lines.append("")

    # ────────────────────── Section 6: Rapid Output (blocks 76-90) ──────────────────────
    lines.append("## Section 6: Rapid Output Edge Cases")
    lines.append("Blocks with many lines to test pyte screen + render pipeline.")
    lines.append("")
    for i in range(76, 91):
        cmd = f"echo 'Rapid block {i}'; seq 1 50 | while read n; do echo 'Rapid line $n for block {i}'; done"
        lines.append(generate_cmd_block(cmd, generate_large_output(f"Rapid block {i}", 50)))
        lines.append("")

    # ────────────────────── Section 7: Special Characters (blocks 91-100) ──────────────────────
    lines.append("## Section 7: Special Characters & Edge Cases")
    lines.append("Blocks with Unicode, ANSI sequences, long lines, empty output.")
    lines.append("")
    for i in range(91, 101):
        lines.append(f"### Edge Case Note {i}")
        lines.append(f"Edge case note #{i} with unicode: äöüÄÖÜß€™®©—–•…")
        lines.append("")
        edge_cmd = f"echo 'Edge case {i} unicode äöü'; echo 'brackets []{{}}()'; echo 'pipes || && ;;'; echo 'quotes \"\\'\\\"\\$\\`'"
        edge_output = generate_large_output(f"Edge case {i} unicode äöü", 60)
        lines.append(generate_cmd_block(edge_cmd, edge_output))
        lines.append("")

    # ────────────────────── Section 8: Final Stress (blocks 101-110) ──────────────────────
    lines.append("## Section 8: Final Stress")
    lines.append("The heaviest blocks to push performance to the limit.")
    lines.append("")
    for i in range(101, 111):
        lines.append(f"### Final Note {i}")
        lines.append(f"Heavy final note #{i}. " * 15)
        lines.append("")
        final_cmd = f"echo 'Final block {i}'; seq 1 80 | while read n; do echo 'Final line $n with lots of padding to make each line really long for block {i} to stress the render pipeline'; done"
        lines.append(generate_cmd_block(final_cmd, generate_large_output(f"Final block {i}", 80)))
        lines.append("")

    # ────────────────────── Write output ──────────────────────
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write("\n".join(lines))
    print(f"Generated {output_path} ({sum(1 for l in lines if l.strip().startswith('```bash'))} bash blocks, "
          f"{sum(1 for l in lines if l.strip().startswith('```text'))} text output blocks, "
          f"{sum(1 for l in lines if l.strip().startswith('##'))} note blocks)")


def generate_cmd_block(cmd: str, output: str, uid: int = 0) -> str:
    meta = f"(uid:{uid})" if uid else ""
    return f"```bash{meta}\n{cmd}\n```\n\n```text\n{output}\n```"


def generate_large_output(base: str, count: int) -> str:
    return "\n".join(f"Line {j}: {base} — padding to make line wider {'x' * 40}" for j in range(count))


def generate_large_output_from_list(items: list) -> str:
    return "\n".join(items)


if __name__ == "__main__":
    generate("scripts/performance_check_notebook.md")
