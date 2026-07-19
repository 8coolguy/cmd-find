# SSH into a server with a custom port
# Tags: ssh, remote
# @param user | Username | text
# @param host | Hostname or IP | text
# @param port | SSH port | number | 22
ssh -p {{port}} {{user}}@{{host}}
