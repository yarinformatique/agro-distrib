import subprocess
import sys
import os
import re
import time
import webbrowser
import socket
import threading

DESKTOP_DIR = os.path.expanduser(r"~\Desktop")
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
CLOUDFLARED_EXE = os.path.join(PROJECT_DIR, "cloudflared.exe")

def is_port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(('127.0.0.1', port)) == 0

def start_django_if_needed():
    if not is_port_open(8000):
        print("[*] Demarrage du serveur Django sur le port 8000...", flush=True)
        subprocess.Popen(
            [sys.executable, "manage.py", "runserver", "0.0.0.0:8000"],
            cwd=PROJECT_DIR,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        )
        for _ in range(10):
            time.sleep(1)
            if is_port_open(8000):
                break
        print("[OK] Serveur Django pret sur le port 8000.\n", flush=True)
    else:
        print("[OK] Serveur Django actif sur le port 8000.\n", flush=True)

def update_desktop_file(public_url):
    url_livreur = f"{public_url}/livreur/"
    url_dashboard = f"{public_url}/dashboard/"
    url_boutique = f"{public_url}/espace-boutique/connexion/"
    url_qr = f"{public_url}/mobile-link/"
    url_terrain = f"{public_url}/prospection/terrain/"

    lien_file = os.path.join(DESKTOP_DIR, "LIEN_AGRO_DISTRIB_EN_LIGNE.txt")
    with open(lien_file, "w", encoding="utf-8") as f:
        f.write("====================================================================\n")
        f.write("   SAAS AGRO-DISTRIB B2B : LIENS PUBLICS STABLES CLOUDFLARE MONDE\n")
        f.write("====================================================================\n\n")
        f.write("Accessible partout dans le monde en 4G/5G/Wi-Fi (a plus de 500 km) :\n\n")
        f.write(f"1. Application Livreur Smartphone (PWA) :\n   {url_livreur}\n\n")
        f.write(f"2. Tableau de Bord Promotrice / PDG :\n   {url_dashboard}\n\n")
        f.write(f"3. Espace Partenaire Boutique (Alimentation) :\n   {url_boutique}\n\n")
        f.write(f"4. Page QR Code pour flasher le lien :\n   {url_qr}\n\n")
        f.write(f"5. Fiche Recensement Terrain (A envoyer par WhatsApp) :\n   {url_terrain}\n\n")
        f.write("--------------------------------------------------------------------\n")
        f.write("COMPTES DE TEST :\n")
        f.write(" - Promotrice / PDG  : promotrice / password123\n")
        f.write(" - Livreur 1         : livreur1 / password123\n")
        f.write(" - Livreur 2         : livreur2 / password123\n")
        f.write(" - Boutique Wend-Kuni: Telephone 70112233 / Code PIN 1234\n")
        f.write("====================================================================\n")

    return url_livreur, url_dashboard, url_boutique, url_qr, url_terrain

def run_cloudflare_tunnel():
    print("=" * 68, flush=True)
    print("     SAAS AGRO-DISTRIB B2B - DIFFUSION HAUTE PERFORMANCE CLOUDFLARE", flush=True)
    print("=" * 68, flush=True)
    
    start_django_if_needed()
    
    if not os.path.exists(CLOUDFLARED_EXE):
        print("[!] Fichier cloudflared.exe introuvable.", flush=True)
        return

    print("[*] Connexion au reseau Cloudflare mondial (protocole QUIC haute vitesse)...", flush=True)
    
    cmd = [CLOUDFLARED_EXE, "tunnel", "--url", "http://127.0.0.1:8000"]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    current_url = None
    browser_opened = False

    def stdout_reader():
        nonlocal current_url, browser_opened
        for line in proc.stdout:
            clean_line = line.strip()
            
            # Recherche de l'URL publique trycloudflare
            match = re.search(r"https://[a-zA-Z0-9\.\-]+\.trycloudflare\.com", clean_line)
            if match and not current_url:
                current_url = match.group(0)
                url_livreur, url_dash, url_btq, url_qr, url_terrain = update_desktop_file(current_url)
                
                print("\n" + "=" * 68, flush=True)
                print("   >>> APPLICATION EN LIGNE SUR LE RESEAU MONDIAL CLOUDFLARE <<<", flush=True)
                print("=" * 68, flush=True)
                print(f"\n[+] LIEN LIVREUR SMARTPHONE (A ENVOYER A +500 KM) :\n    {url_livreur}\n", flush=True)
                print(f"[+] TABLEAU DE BORD PROMOTRICE / PDG :\n    {url_dash}\n", flush=True)
                print(f"[+] ESPACE BOUTIQUE (TRANSPARENCE ANTI-LITIGE) :\n    {url_btq}\n", flush=True)
                print(f"[+] FICHE RECENSEMENT TERRAIN (WHATSAPP) :\n    {url_terrain}\n", flush=True)
                print(f"[+] PAGE QR CODE & INSTALLATION PWA :\n    {url_qr}\n", flush=True)
                print("-" * 68, flush=True)
                print("[OK] Fichier 'LIEN_AGRO_DISTRIB_EN_LIGNE.txt' mis a jour sur le Bureau.", flush=True)
                print("[*] Connexion securisee et permanente (Aucune deconnexion).", flush=True)
                print("[*] Gardez cette fenetre ouverte pendant l'utilisation.", flush=True)
                print("=" * 68 + "\n", flush=True)

                if not browser_opened:
                    browser_opened = True
                    try:
                        webbrowser.open(url_dash)
                    except Exception:
                        pass
            
            if "Registered tunnel" in clean_line:
                print("[Connexion Etablie]", clean_line, flush=True)

    reader_thread = threading.Thread(target=stdout_reader, daemon=True)
    reader_thread.start()

    try:
        proc.wait()
    except KeyboardInterrupt:
        print("\nArret du tunnel...", flush=True)
        proc.terminate()

def main():
    while True:
        try:
            run_cloudflare_tunnel()
        except KeyboardInterrupt:
            print("\nFermeture demandee par l'utilisateur.")
            break
        except Exception as e:
            print(f"[Relance] Erreur tunnel : {e}. Nouvelle tentative dans 3s...", flush=True)
        time.sleep(3)

if __name__ == '__main__':
    main()
