cd /srv/soweego_production/soweego/
/usr/bin/tmux kill-session -t pipeline-musicbrainz
/usr/bin/tmux new-session -d -s "pipeline-musicbrainz"
/usr/bin/tmux send-keys -t pipeline-musicbrainz:0 "./docker/launch_pipeline.sh -c ../prod_cred.json -s /srv/soweego_production/musicbrainz-shared/ musicbrainz --no-upload --validator" ENTER
