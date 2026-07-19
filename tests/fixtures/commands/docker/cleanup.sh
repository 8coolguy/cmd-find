# A command with environment variables and pipes
# Tags: docker, cleanup, dangerous
docker ps -aq | xargs docker rm -f $FLAG
