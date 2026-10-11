# SAAS AGRO-DISTRIB B2B (VAN SALES & DISTRIBUTION MULTI-VILLES) 🥭📦

Application web et mobile (PWA) de distribution B2B et van sales adaptée au marché ouest-africain (Burkina Faso : Bobo-Dioulasso, Ouagadougou).

---

## 🚀 1. Démarrage Rapide

Double-cliquez sur le lanceur situé sur votre Bureau Windows :  
👉 **`LANCER_AGRO_DISTRIB.bat`**

Ou via le terminal PowerShell :
```powershell
cd c:\Users\USER\Desktop\agro_distrib
python manage.py runserver 0.0.0.0:8000
```

---

## 📲 2. Accès sur Smartphone & QR Code

1. Connectez votre smartphone au même réseau Wi-Fi que votre ordinateur.
2. Ouvrez la page dédiée **Accès Smartphone & QR Code** :
   👉 **[http://127.0.0.1:8000/mobile-link/](http://127.0.0.1:8000/mobile-link/)**
3. Scannez le **QR Code** qui s'affiche directement à l'écran avec votre smartphone :
   - URL Smartphone directe : **`http://192.168.100.8:8000/livreur/`**
4. Installez l'application en 1 clic (PWA) :
   - **Sur Android (Chrome)** : Menu 3 points &rarr; *« Installer l'application »* ou *« Ajouter à l'écran d'accueil »*.
   - **Sur iPhone (Safari)** : Bouton Partager &rarr; *« Sur l'écran d'accueil »*.

---

## 👥 3. Comptes & Espaces de Démonstration

| Espace & Rôle | Identifiant / Accès | Mot de passe / PIN | Fonctionnalités Clés |
|---|---|---|---|
| **👑 Promotrice (PDG)** | `promotrice` | `password123` | Dashboard DG en FCFA, Expéditions inter-villes (Bobo &rarr; Ouaga), Attribution des tournées, Ordres de mission et consignes de prix, Créances et reporting mensuel. |
| **🛵 Livreur Terrain (PWA)** | `livreur1` | `password123` | Application mobile PWA : Tri GPS par proximité, bouton « 🚀 DÉMARRER » avec guidage vocal Google Maps et carte en direct, saisie tactile des ventes, reçu WhatsApp. |
| **🏪 Boutique Partenaire** | Portail Boutiques &rarr; *Wend-Kuni* | PIN : `1234` | Espace boutique anti-litige : Suivi des livraisons, bouton « Confirmer la réception », déclaration directe de paiements Orange Money / Moov Money. |
| **🛵 Livreur Relais 2** | `livreur2` | `password123` | Chauffeur / livreur secondaire pour tester le multi-véhicules. |

---

## 🌟 4. Les Nouveaux Modules Professionnels

### 1. 📦 Expéditions Inter-Villes & Sociétés de Livraison (Bobo-Dioulasso &rarr; Ouagadougou)
- Envoi de cargaisons de produits par la Promotrice vers les hubs ou transporteurs partenaires (ex: TSR Express, Rakieta, Transporteur tiers).
- Sélection des produits en sachets, pots, cartons, kilogrammes avec **valeur marchande exacte en FCFA**.
- Consignes générales d'acheminement et consignes spécifiques de répartition par boutique.
- Génération et impression du **Bordereau Officiel d'Expédition / Lettre de Voiture** avec décharges et signatures.

### 2. 🎯 Ordres de Mission & Consignes Assignées aux Livreurs
- La Promotrice assigne des consignes précises aux livreurs pour chaque tournée :
  - Alimentation ciblée
  - Articles et quantités exigées
  - Montant exact à encaisser (FCFA)
  - Consignes de négociation ou de règlement (ex: *« Exiger paiement comptant en espèces ou Orange Money, vérifier réassort »*).
- Sur son smartphone, le livreur dispose d'une section dédiée **« 🎯 Mes Missions du Jour »** avec bouton **« 🚀 Démarrer »** qui lance directement l'itinéraire et pré-remplit la commande !

### 3. 🏪 Portail Partenaire / Espace Alimentation (Sécurité Anti-Litige)
- Permet aux alimentations et boutiques de se connecter via un code PIN simple (`1234`).
- **Confirmation contradictoire** : La boutique confirme avoir bien reçu les quantités et montants avec horodatage automatique.
- **Déclaration de Paiement** : La boutique déclare ses règlements par Mobile Money (Orange Money, Moov Money) avec référence de transaction.
- Élimine tout risque de contestation ou de désaccord entre le livreur et la boutique !

### 4. 🛰️ Guidage GPS Automatique & "DÉMARRER" Instantané
- Localisation silencieuse en tâche de fond (`watchPosition`) sans sollicitations répétitives.
- Bouton **« 🚀 DÉMARRER »** :
  - Lance immédiatement la navigation vocale guidée virage par virage dans Google Maps (`origin=...&destination=...&travelmode=driving&dir_action=navigate`).
  - Affiche une carte interactive Leaflet intégrée avec tracé entre le livreur et la boutique, distance exacte en mètres/km et temps de trajet estimé.

---

## 🧪 5. Tests Automatisés

8 tests unitaires et d'intégration couvrent l'intégralité du cycle :
```powershell
python manage.py test
```
Résultat : `Ran 8 tests ... OK`
