# Find files larger than a given size
# Tags: system, disk, find
# @param size | Minimum file size (e.g. 100M, 1G) | text | 100M
find . -type f -size +{{size}} -exec ls -lh {} \;
