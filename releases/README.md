# Dataset releases

Frozen, citable releases of the curated dataset, one directory per release (`releases/<YYYY-MM-DD>_<name>/`), each committed and tagged in git. Releases arrive in Phase 4 (`make release NAME=<name>`, see `PLAN.md` §6.7); until then this README is the only file here.

Keep this file: it makes `releases/` part of every clone. `docker-compose.yml` bind-mounts `./releases`, and the Docker daemon would create a missing directory as root, which neither your user nor a later `git pull` could write to.
