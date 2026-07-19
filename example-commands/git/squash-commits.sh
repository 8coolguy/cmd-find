# Interactively rebase the last N commits
# Tags: git, rebase
# @param count | Number of commits | number | 3
git rebase -i HEAD~{{count}}
