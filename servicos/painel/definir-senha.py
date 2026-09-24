#!/usr/bin/python3
"""Define a senha do painel.

    sudo ./definir-senha.py

A senha nunca fica em disco: o que se guarda e o hash scrypt dela.
"""
import getpass
import secrets
import sys

import nucleo

if __name__ == '__main__':
    senha = getpass.getpass('senha nova: ')
    if len(senha) < 10:
        sys.exit('senha curta demais; use pelo menos 10 caracteres')
    if senha != getpass.getpass('de novo: '):
        sys.exit('as duas não bateram')
    config = nucleo.le_config()
    config['senha'] = nucleo.cifra_senha(senha)
    config.setdefault('segredo', secrets.token_urlsafe(48))
    config.setdefault('usuario', 'jarl')
    nucleo.grava_config(config)
    print(f'guardado em {nucleo.CONFIG} (só o hash)')
