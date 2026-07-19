# Execute a shell inside a running container
# Tags: docker, exec
# @param container | Container name or ID | text
# @param shell | Shell to use | choice:bash,sh,zsh | bash
docker exec -it {{container}} /bin/{{shell}}
