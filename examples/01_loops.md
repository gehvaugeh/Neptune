# Bash Tutorial: For Loops and File Iteration

Welcome to the Neptune Bash Notebook on **Loops**. This tutorial will guide you through the various ways to repeat actions in Bash, from simple lists to iterating over files.

## 1. The Basic For Loop

The most common loop in Bash is the `for` loop. It iterates over a list of items.

```bash
for name in Alice Bob Charlie; do
    echo "Hello, $name!"
done
```

## 2. Looping Over Ranges

You can use brace expansion `{start..end}` to generate a range of numbers.

```bash
echo "Counting to 5:"
for i in {1..5}; do
    echo "Number: $i"
done
```

You can also specify an increment: `{start..end..step}`

```bash
echo "Even numbers up to 10:"
for i in {0..10..2}; do
    echo "i = $i"
done
```

## 3. Looping Over Files (The Globbing Method)

One of the most powerful uses of loops in Bash is processing files. Use wildcards (globs) to match files.

First, let's create some dummy files to play with:

```bash
mkdir -p loop_demo
touch loop_demo/file1.txt loop_demo/file2.log loop_demo/script.sh
ls loop_demo
```

Now, let's loop over all files in that directory:

```bash
for file in loop_demo/*; do
    echo "Processing $(basename "$file")"
done
```

## 4. C-Style For Loops

Bash also supports C-style syntax, which is useful when you need an index.

```bash
for ((i=0; i<5; i++)); do
    echo "Iteration $i"
done
```

## 5. Advanced: Reading a File Line-by-Line

While `for` loops are great for lists, `while` loops combined with `read` are better for reading files line-by-line to handle spaces correctly.

```bash
# Create a file with spaces in names
cat <<EOF > names.txt
John Doe
Jane Smith
Common User
EOF

# Read it line by line
while IFS= read -r line; do
    echo "Full Name: $line"
done < names.txt
```

## Cleanup

```bash
rm -rf loop_demo names.txt
```
