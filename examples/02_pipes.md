# Bash Tutorial: Redirection, Streams, and Pipes

Mastering the flow of data is essential for shell productivity. This tutorial covers how to redirect inputs/outputs and how to connect commands using pipes.

## 1. Standard Streams

Every process has three standard streams:
- `stdin` (0): Standard Input
- `stdout` (1): Standard Output
- `stderr` (2): Standard Error

## 2. Redirecting Output to a File

Use `>` to overwrite a file and `>>` to append to it.

```bash
echo "This is a new file" > output.txt
echo "This is an appended line" >> output.txt
cat output.txt
```

## 3. Redirecting Standard Error

Sometimes commands fail. You can capture the error message specifically using `2>`.

```bash
ls non_existent_file 2> error.log
echo "Error captured in log:"
cat error.log
```

You can redirect both `stdout` and `stderr` to the same place using `&>`:

```bash
ls . non_existent_file &> combined.log
cat combined.log
```

## 4. Using Pipes (`|`)

Pipes allow you to use the output of one command as the input for another. This is the "Unix Philosophy" in action.

```bash
# Get the top 3 largest files in the current directory
ls -lh | sort -k 5 -h -r | head -n 3
```

## 5. The `tee` Command

`tee` is like a "T-junction" for data: it sends output to both a file AND `stdout`.

```bash
echo "Hello Neptune!" | tee hello.txt
```

## 6. Advanced: Process Substitution

Process substitution allows you to treat the output of a command as a file. This is useful for commands that expect file arguments.

```bash
# Compare the output of two commands
diff <(echo "List A"; ls) <(echo "List A"; ls -a)
```

## Cleanup

```bash
rm output.txt error.log combined.log hello.txt
```
