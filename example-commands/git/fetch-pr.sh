# Fetch a pull request from GitHub by PR number
# Tags: git, github, pr
# @param pr_number | Pull request number | number
# @param branch | Local branch name | text | pr-{{pr_number}}
git fetch origin pull/{{pr_number}}/head:{{branch}}
