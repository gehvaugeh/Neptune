# Bash Tutorial: Globbing and Wildcards

Globbing is the process by which Bash expands wildcards into a list of matching filenames. Understanding globbing makes file management much faster.

## Setup

Let's create a sandbox directory to experiment:

```bash
mkdir -p glob_demo
touch glob_demo/apple.txt glob_demo/banana.txt glob_demo/cherry.jpg glob_demo/date.txt glob_demo/eggplant.jpg
ls glob_demo
```

## 1. The Asterisk (`*`)

The `*` matches any number of characters (including zero).

```bash
echo "All .txt files:"
ls glob_demo/*.txt

echo "Everything starting with 'a':"
ls glob_demo/a*
```

## 2. The Question Mark (`?`)

The `?` matches exactly one character.

```bash
# Match 'date.txt' but not 'apple.txt'
ls glob_demo/????.txt
```

## 3. Character Classes (`[]`)

Brackets allow you to match a specific set or range of characters.

```bash
# Match files starting with 'a' or 'b'
ls glob_demo/[ab]*

# Match files starting with letters 'a' through 'c'
ls glob_demo/[a-c]*
```

## 4. Brace Expansion (`{}`)

Brace expansion is technically not globbing (it doesn't check the filesystem), but it's often used with it. It generates arbitrary strings.

```bash
# Create multiple directories at once
mkdir -p glob_demo/{dir1,dir2,dir3}
ls -F glob_demo
```

## 5. Advanced: Extended Globbing

If `extglob` is enabled, you get powerful pattern matching like `@(pattern1|pattern2)`.

```bash
shopt -s extglob
# Match everything EXCEPT .jpg files
ls glob_demo/!(*.jpg)
```

## 6. Recursive Globbing (`**`)

With `globstar` enabled, `**` matches all files and zero or more directories.

```bash
shopt -s globstar
ls -d glob_demo/**
```

## Cleanup

```bash
rm -rf glob_demo
```
