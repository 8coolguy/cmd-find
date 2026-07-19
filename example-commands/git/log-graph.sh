# Show a compact git log with graph (customizable depth)
# Tags: git, log
# @param count | Number of commits to show | number | 20
git log --oneline --graph --all --decorate -{{count}}
