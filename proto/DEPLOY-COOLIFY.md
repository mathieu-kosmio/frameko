# Déploiement Frameko sur Coolify (via GHCR)

Le build de l'image Docker se fait **dans GitHub Actions** (pas sur votre machine) et
publie l'image sur **GHCR** (GitHub Container Registry). **Coolify tire l'image** et la
déploie. Vous n'avez donc rien à builder localement.

```
  push sur main ──► GitHub Actions (build) ──► ghcr.io/mathieu-kosmio/frameko:latest
                                                          │
                                                          ▼
                                                 Coolify (pull + run)
                                          ┌──────────────┴───────────────┐
                                       service web (8080)        service mcp (8765)
```

## 1. Publier l'image (automatique)

Le workflow [`.github/workflows/docker-publish.yml`](../.github/workflows/docker-publish.yml)
se déclenche à chaque `push` sur `main` touchant `proto/` (ou manuellement via l'onglet
**Actions → Build & publish Docker image → Run workflow**).

Il produit les tags : `latest`, `sha-<court>`, et `vX.Y.Z` sur les tags Git.
Rien à configurer : il utilise le `GITHUB_TOKEN` intégré (permission `packages: write`).

Vérifier après le 1er run : **GitHub → onglet du dépôt → Packages → `frameko`**.

## 2. Rendre l'image accessible à Coolify

Par défaut un package GHCR est **privé**. Deux options :

- **Simple (proto)** — le rendre public : *Packages → frameko → Package settings →
  Change visibility → Public*. Coolify le tire alors sans authentification.
- **Privé** — dans Coolify, ajouter un *Docker Registry* (`ghcr.io`) avec un
  **Personal Access Token** GitHub (scope `read:packages`).

## 3. Créer la ressource dans Coolify

1. **+ New → Resource → Docker Compose** (Empty / depuis Git, au choix).
2. Coller le contenu de [`docker-compose.coolify.yml`](docker-compose.coolify.yml)
   (ou pointer Coolify sur ce fichier dans le dépôt : *Compose path* = `proto/docker-compose.coolify.yml`).
3. Vérifier que l'image référencée correspond bien à votre dépôt
   (`ghcr.io/mathieu-kosmio/frameko:latest`).

## 4. Variables d'environnement (onglet Environment Variables)

| Variable | Rôle | Obligatoire |
|---|---|---|
| `DATABASE_URL` | connexion Postgres admin (Supabase) | ✅ |
| `APP_DATABASE_URL` | rôle applicatif `frameko_app` (RLS, auto-évaluations) | ✅ |
| `WEB_SECRET_KEY` | clé de signature des sessions de la console web | ✅ (service web) |
| `USE_POOLER` | `1` pour passer par le pooler Supabase (recommandé en conteneur) | ⚠️ voir §6 |
| `DATABASE_POOLER_URL` | URL du pooler Supavisor (transaction, IPv4) | ⚠️ si `USE_POOLER=1` |

> Ne jamais committer ces secrets : ils se renseignent **uniquement dans Coolify**
> (le `.env` reste hors image, cf. `.dockerignore`).

## 5. Domaines & HTTPS

Dans Coolify, pour **chaque service exposé**, définir un domaine (FQDN). Le proxy
intégré (Traefik) route et provisionne le **certificat Let's Encrypt** automatiquement —
inutile de déployer Caddy.

| Service | Port interne | Domaine suggéré | Sert |
|---|---|---|---|
| `web` | 8080 | `frameko.votredomaine.fr` | la console web |
| `mcp` | 8765 | `api.frameko.votredomaine.fr` | l'API MCP (`/mcp/`, `/health`) |

Le header `Authorization: Bearer <jeton>` (jeton d'organisation) est transmis tel quel
au backend MCP.

## 6. Réseau base de données (le piège à éviter)

Sur un VPS Coolify **IPv4-only**, **deux** des trois endpoints Supabase sont injoignables :
le **direct** (`db.<ref>.supabase.co:5432`) ET le **transaction pooler** (`:6543`) sont
**IPv6 par défaut** → `Network is unreachable`. Le seul endpoint IPv4 (hors add-on payant)
est le **Session pooler** (port **5432** sur l'hôte `…pooler.supabase.com`).

Dans Supabase : bouton **Connect** (en haut) → **Session pooler** → copier l'URI. Puis :

```
DATABASE_URL=postgresql://postgres.<ref>:<password>@aws-<n>-<region>.pooler.supabase.com:5432/postgres
APP_DATABASE_URL=postgresql://frameko_app.<ref>:<password>@aws-<n>-<region>.pooler.supabase.com:5432/postgres
# Optionnel (équivalent, si on préfère garder DATABASE_URL en direct pour le local) :
# USE_POOLER=1 + DATABASE_POOLER_URL / APP_DATABASE_POOLER_URL sur le Session pooler
```

> Mettre directement `DATABASE_URL` (et `APP_DATABASE_URL`) sur le Session pooler est le
> plus simple : ça marche quel que soit `USE_POOLER`. Au démarrage, le conteneur logge
> l'hôte réellement utilisé (`[frameko/db] pool 'admin' → …`) — pratique pour vérifier.

## 7. Déployer & vérifier

1. **Deploy** dans Coolify (il tire l'image et démarre les services).
2. Sonde MCP : `GET https://api.frameko.votredomaine.fr/health` → `200`.
3. Console : ouvrir `https://frameko.votredomaine.fr` → les référentiels se chargent.

> 1er démarrage : chaque service télécharge le modèle d'embedding (~50 Mo) dans son
> volume `model-cache-*`. Les redémarrages suivants sont immédiats (cache persistant).

## 8. Mises à jour

À chaque `push` sur `main`, GitHub Actions republie `:latest`. Pour redéployer :
- **manuel** : bouton *Redeploy* dans Coolify ;
- **auto** : activer un *Webhook* Coolify appelé en fin de workflow, ou la surveillance
  d'image de Coolify (*Watch* / *Automatic deployment*).

## 9. Provisionner les organisations (auto-évaluation)

Les auto-évaluations exigent un jeton d'organisation (isolation RLS). Émettre un jeton
une fois la base accessible :

```bash
python scripts/create_org.py --slug acme --name "ACME Fleurs"   # → imprime le jeton (1 seule fois)
```

(À lancer depuis un environnement ayant `DATABASE_URL`/`APP_DATABASE_URL`, ou via un
*one-off* container Coolify.)
