# MedMap

A hospital-placement recommendation tool built for **TigerHacks26**.

MedMap suggests where a new hospital should be built so that it cuts driving
distance for the people farthest from care and takes pressure off existing
hospitals. It combines census population, HRSA shortage-area designations, and
CMS hospital locations, and shows the results on an interactive map where you
set how much each factor matters.

For other deployment options, see [DEPLOYMENT.md](DEPLOYMENT.md).

## A. Run with Docker

From the repo root:

```bash
docker compose -f docker/docker-compose.yml up --build   # build and start
docker compose -f docker/docker-compose.yml down         # stop and remove the containers
```

The site is at **<http://localhost:8000/>**. The map is at `/map`.

## B. Share a public link with a Cloudflare tunnel

While MedMap is running on port 8000, run these in a second terminal:

```powershell
winget install --id Cloudflare.cloudflared         # install cloudflared (one time)
cloudflared --version                              # check that the install worked
cloudflared tunnel --url http://localhost:8000/    # open the tunnel
```

The last command prints a public `https://<random-words>.trycloudflare.com`
link that anyone can open. No Cloudflare account is needed. The link works only
while that terminal stays open. Press `Ctrl+C` to close the tunnel.
