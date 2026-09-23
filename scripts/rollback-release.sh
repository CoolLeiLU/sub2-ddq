#!/usr/bin/env bash
set -Eeuo pipefail

release_sha=${1:?release SHA is required}
if [[ ! ${release_sha} =~ ^[0-9a-f]{40}$ ]]; then
    echo "invalid release SHA" >&2
    exit 2
fi

base_dir=/opt/bot-mcp
shared_dir=${base_dir}/shared
release_dir=${base_dir}/releases/${release_sha}
if [[ ! -d ${release_dir} || ! -f ${release_dir}/.release.env || ! -f ${shared_dir}/.env ]]; then
    echo "requested release is unavailable" >&2
    exit 3
fi

current_release=$(readlink -f -- "${base_dir}/current" 2>/dev/null || true)
current_sha=$(cat "${base_dir}/deployed-sha" 2>/dev/null || true)
if [[ -z ${current_release} || ! ${current_sha} =~ ^[0-9a-f]{40}$ ]]; then
    echo "current release metadata is unavailable" >&2
    exit 4
fi
expected_previous=$(cat "${current_release}/previous-sha" 2>/dev/null || true)
if [[ ${expected_previous} != "${release_sha}" ]]; then
    echo "database-safe rollback is limited to the immediately previous release" >&2
    exit 5
fi

backup_file=/opt/bot-mcp/backups/predeploy-${current_sha}.sql
if [[ ! -s ${backup_file} ]]; then
    echo "no pre-deploy database dump for ${current_sha} is available" >&2
    exit 6
fi
docker stop sub2api-scheduler-mcp >/dev/null || true
if ! docker exec -i sub2api-scheduler-postgres \
    psql -v ON_ERROR_STOP=1 -U guardian -d guardian < "${backup_file}" >/dev/null 2>&1; then
    echo "database restore failed; rollback aborted" >&2
    exit 7
fi

docker compose \
    --project-name bot-mcp \
    --env-file "${shared_dir}/.env" \
    --env-file "${release_dir}/.release.env" \
    --file "${release_dir}/compose.yaml" \
    --file "${release_dir}/compose.deploy.yaml" \
    up -d --remove-orphans

for _ in $(seq 1 60); do
    status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' sub2api-scheduler-mcp 2>/dev/null || true)
    if [[ ${status} == healthy ]]; then
        temporary_link=${base_dir}/.current.${release_sha}
        ln -sfn -- "${release_dir}" "${temporary_link}"
        mv -Tf -- "${temporary_link}" "${base_dir}/current"
        printf '%s\n' "${release_sha}" > "${base_dir}/deployed-sha"
        echo "rolled back to ${release_sha}"
        exit 0
    fi
    sleep 2
done

docker logs --tail 120 sub2api-scheduler-mcp >&2 || true
exit 8
