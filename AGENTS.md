# Heimdall Nexus: agent instructions

Read and follow [docs/PADROES-GENESISMODS.md](docs/PADROES-GENESISMODS.md)
before any change. Priorities: security first, then simplicity and clear
step-by-step guidance for the user, then a clean Valheim-themed look using the
GenesisMods tokens and components.

- Code, logs and comments in English; player-facing text in pt-BR.
- The Sagas port plan and status live in docs/SAGAS-EXTENSION.md.
- Development happens on `dev/sagas`; the user tests it on a private VM by
  `git pull` + `sudo ./deploy/update.sh`. Never test on production.
