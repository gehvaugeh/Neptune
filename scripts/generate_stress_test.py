import argparse
import random
import time

def generate_markdown(num_blocks, output_file):
    with open(output_file, 'w') as f:
        f.write(f"# Stress Test Notebook - {num_blocks} blocks\n\n")

        for i in range(num_blocks):
            block_type = random.choice(["NOTE", "CMD"])
            if block_type == "NOTE":
                f.write(f"## Note Block {i}\n")
                f.write("This is a note block used for stress testing. " * 10 + "\n\n")
            else:
                f.write("```bash\n")
                f.write(f"echo 'Command Block {i}'\n")
                f.write("```\n")
                # Add large output simulation
                f.write("```text\n")
                for j in range(50):
                    f.write(f"Line {j}: This is a simulated large output for command block {i}. " * 5 + "\n")
                f.write("```\n\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a stress test markdown notebook.")
    parser.add_argument("-n", "--num-blocks", type=int, default=100, help="Number of blocks to generate")
    parser.add_argument("-o", "--output", default="stress_test.md", help="Output filename")
    args = parser.parse_args()

    print(f"Generating {args.num_blocks} blocks into {args.output}...")
    generate_markdown(args.num_blocks, args.output)
    print("Done.")
