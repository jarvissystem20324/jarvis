"""8.0: six more interface languages, merged into i18n.STRINGS at import.

Each language is a list in the same order as KEYS (a test checks the lengths
match), which keeps a 66-string table per language readable.
"""

from __future__ import annotations

KEYS = [
    "Chat", "Image Gen", "Code", "THINKING MODE", "Settings", "Check for Updates", "Ready", "Thinking...",
    "Listening...", "Generating image...", "Stopped", "Send", "Stop", "Save", "Close", "Allow once", "Deny",
    "Update now", "Later", "Open Folder", "Open Image", "Generate Image", "Test", "Copy reply", "Copy code", "Find",
    "Export", "Shortcuts", "API keys", "Models per mode", "configured", "not set", "testing…", "works",
    "key rejected", "valid, but no credit", "rate limited — try again shortly", "free", "paid",
    "JARVIS needs permission", "Allow this?", "Run a command on this PC", "Write to a file", "Delete a file",
    "Capture your screen", "Read a file into the conversation", "Send project code to an AI provider",
    "Run this project's test suite", "Fetch something over the network", "Let the agent carry out this plan",
    "Low", "Mid", "High", "Max", "Hyperdrive", "Security", "Update available", "You have", "Downloading...",
    "Image generation", "Size:", "Quality:", "Generated image will appear here",
    "Ask JARVIS anything... (/image prompt to generate)", "Change a Windows setting", "Hands-free",
]

TABLES: dict[str, tuple[str, str, list[str]]] = {
    "de": ("Deutsch", "Der Nutzer verwendet die deutsche Oberfläche. Antworte auf Deutsch, außer der Nutzer schreibt in einer anderen Sprache.", [
        "Chat", "Bilder", "Code", "DENKMODUS", "Einstellungen", "Nach Updates suchen", "Bereit", "Denkt nach...",
        "Hört zu...", "Bild wird erzeugt...", "Gestoppt", "Senden", "Stopp", "Speichern", "Schließen", "Einmal erlauben",
        "Ablehnen", "Jetzt aktualisieren", "Später", "Ordner öffnen", "Bild öffnen", "Bild erzeugen", "Testen",
        "Antwort kopieren", "Code kopieren", "Suchen", "Exportieren", "Tastenkürzel", "API-Schlüssel", "Modelle pro Modus",
        "eingerichtet", "nicht gesetzt", "teste…", "funktioniert", "Schlüssel abgelehnt", "gültig, aber kein Guthaben",
        "Ratenlimit — gleich noch einmal versuchen", "kostenlos", "kostenpflichtig", "JARVIS bittet um Erlaubnis",
        "Erlauben?", "Einen Befehl auf diesem PC ausführen", "In eine Datei schreiben", "Eine Datei löschen",
        "Bildschirm aufnehmen", "Eine Datei ins Gespräch laden", "Projektcode an einen KI-Anbieter senden",
        "Die Tests dieses Projekts ausführen", "Etwas aus dem Netz laden", "Den Agenten diesen Plan ausführen lassen",
        "Niedrig", "Mittel", "Hoch", "Maximal", "Hyperantrieb", "Sicherheit", "Update verfügbar", "Installiert",
        "Wird heruntergeladen...", "Bilderzeugung", "Größe:", "Qualität:", "Das erzeugte Bild erscheint hier",
        "Frag JARVIS etwas... (/image Beschreibung für ein Bild)", "Eine Windows-Einstellung ändern", "Freihändig"]),
    "es": ("Español", "El usuario usa la interfaz en español. Responde en español salvo que el usuario escriba en otro idioma.", [
        "Chat", "Imágenes", "Código", "MODO DE PENSAR", "Ajustes", "Buscar actualizaciones", "Listo", "Pensando...",
        "Escuchando...", "Generando imagen...", "Detenido", "Enviar", "Detener", "Guardar", "Cerrar", "Permitir una vez",
        "Denegar", "Actualizar ahora", "Más tarde", "Abrir carpeta", "Abrir imagen", "Generar imagen", "Probar",
        "Copiar respuesta", "Copiar código", "Buscar", "Exportar", "Atajos", "Claves de API", "Modelos por modo",
        "configurado", "sin configurar", "probando…", "funciona", "clave rechazada", "válida, pero sin crédito",
        "límite de uso — inténtalo en un momento", "gratis", "de pago", "JARVIS necesita permiso", "¿Permitir esto?",
        "Ejecutar un comando en este PC", "Escribir en un archivo", "Borrar un archivo", "Capturar tu pantalla",
        "Leer un archivo en la conversación", "Enviar código del proyecto a un proveedor de IA",
        "Ejecutar las pruebas de este proyecto", "Descargar algo de la red", "Dejar que el agente ejecute este plan",
        "Bajo", "Medio", "Alto", "Máximo", "Hiperimpulso", "Seguridad", "Actualización disponible", "Tienes",
        "Descargando...", "Generación de imágenes", "Tamaño:", "Calidad:", "La imagen generada aparecerá aquí",
        "Pregunta lo que quieras a JARVIS... (/image descripción para una imagen)", "Cambiar un ajuste de Windows",
        "Manos libres"]),
    "fr": ("Français", "L'utilisateur utilise l'interface en français. Réponds en français sauf si l'utilisateur écrit dans une autre langue.", [
        "Discussion", "Images", "Code", "MODE DE RÉFLEXION", "Paramètres", "Rechercher des mises à jour", "Prêt",
        "Réflexion...", "Écoute...", "Création de l'image...", "Arrêté", "Envoyer", "Arrêter", "Enregistrer", "Fermer",
        "Autoriser une fois", "Refuser", "Mettre à jour", "Plus tard", "Ouvrir le dossier", "Ouvrir l'image",
        "Créer l'image", "Tester", "Copier la réponse", "Copier le code", "Rechercher", "Exporter", "Raccourcis",
        "Clés d'API", "Modèles par mode", "configurée", "non définie", "test…", "fonctionne", "clé refusée",
        "valide, mais sans crédit", "limite atteinte — réessayez dans un instant", "gratuit", "payant",
        "JARVIS demande une autorisation", "Autoriser ?", "Exécuter une commande sur ce PC", "Écrire dans un fichier",
        "Supprimer un fichier", "Capturer votre écran", "Lire un fichier dans la conversation",
        "Envoyer le code du projet à un fournisseur d'IA", "Lancer les tests de ce projet", "Télécharger quelque chose",
        "Laisser l'agent exécuter ce plan", "Bas", "Moyen", "Élevé", "Max", "Hyperpropulsion", "Sécurité",
        "Mise à jour disponible", "Vous avez", "Téléchargement...", "Création d'images", "Taille :", "Qualité :",
        "L'image créée apparaîtra ici", "Demandez n'importe quoi à JARVIS... (/image description pour une image)",
        "Modifier un paramètre Windows", "Mains libres"]),
    "pt": ("Português", "O usuário usa a interface em português. Responda em português, a menos que o usuário escreva em outro idioma.", [
        "Conversa", "Imagens", "Código", "MODO DE PENSAR", "Configurações", "Procurar atualizações", "Pronto",
        "Pensando...", "Ouvindo...", "Gerando imagem...", "Parado", "Enviar", "Parar", "Salvar", "Fechar",
        "Permitir uma vez", "Negar", "Atualizar agora", "Mais tarde", "Abrir pasta", "Abrir imagem", "Gerar imagem",
        "Testar", "Copiar resposta", "Copiar código", "Procurar", "Exportar", "Atalhos", "Chaves de API",
        "Modelos por modo", "configurada", "não definida", "testando…", "funciona", "chave recusada",
        "válida, mas sem crédito", "limite atingido — tente de novo em instantes", "grátis", "pago",
        "O JARVIS precisa de permissão", "Permitir isto?", "Executar um comando neste PC", "Gravar em um arquivo",
        "Apagar um arquivo", "Capturar sua tela", "Ler um arquivo na conversa", "Enviar código do projeto a um provedor de IA",
        "Executar os testes deste projeto", "Baixar algo da rede", "Deixar o agente executar este plano",
        "Baixo", "Médio", "Alto", "Máximo", "Hiperpropulsão", "Segurança", "Atualização disponível", "Você tem",
        "Baixando...", "Geração de imagens", "Tamanho:", "Qualidade:", "A imagem gerada aparecerá aqui",
        "Pergunte qualquer coisa ao JARVIS... (/image descrição para uma imagem)", "Alterar uma configuração do Windows",
        "Mãos livres"]),
    "ru": ("Русский", "Пользователь использует русский интерфейс. Отвечай по-русски, если пользователь не пишет на другом языке.", [
        "Чат", "Изображения", "Код", "РЕЖИМ МЫШЛЕНИЯ", "Настройки", "Проверить обновления", "Готово", "Думаю...",
        "Слушаю...", "Создаю изображение...", "Остановлено", "Отправить", "Стоп", "Сохранить", "Закрыть",
        "Разрешить один раз", "Запретить", "Обновить сейчас", "Позже", "Открыть папку", "Открыть изображение",
        "Создать изображение", "Проверить", "Копировать ответ", "Копировать код", "Найти", "Экспорт", "Горячие клавиши",
        "Ключи API", "Модели по режимам", "настроен", "не задан", "проверка…", "работает", "ключ отклонён",
        "действителен, но нет средств", "лимит запросов — попробуйте чуть позже", "бесплатно", "платно",
        "JARVIS просит разрешения", "Разрешить?", "Выполнить команду на этом ПК", "Записать в файл", "Удалить файл",
        "Сделать снимок экрана", "Прочитать файл в разговор", "Отправить код проекта провайдеру ИИ",
        "Запустить тесты проекта", "Загрузить что-то из сети", "Позволить агенту выполнить этот план",
        "Низкий", "Средний", "Высокий", "Максимум", "Гипердрайв", "Безопасность", "Доступно обновление", "У вас",
        "Загрузка...", "Создание изображений", "Размер:", "Качество:", "Здесь появится созданное изображение",
        "Спросите JARVIS о чём угодно... (/image описание — для картинки)", "Изменить настройку Windows",
        "Без рук"]),
    "az": ("Azərbaycanca", "İstifadəçi Azərbaycan dilində interfeysdən istifadə edir. İstifadəçi başqa dildə yazmasa, Azərbaycan dilində cavab ver.", [
        "Söhbət", "Şəkillər", "Kod", "DÜŞÜNMƏ REJİMİ", "Ayarlar", "Yeniləmələri yoxla", "Hazırdır", "Düşünür...",
        "Dinləyir...", "Şəkil yaradılır...", "Dayandırıldı", "Göndər", "Dayandır", "Yadda saxla", "Bağla",
        "Bir dəfə icazə ver", "Rədd et", "İndi yenilə", "Sonra", "Qovluğu aç", "Şəkli aç", "Şəkil yarat", "Yoxla",
        "Cavabı kopyala", "Kodu kopyala", "Tap", "İxrac et", "Qısayollar", "API açarları", "Rejim üzrə modellər",
        "quraşdırılıb", "təyin edilməyib", "yoxlanılır…", "işləyir", "açar rədd edildi", "etibarlıdır, amma kredit yoxdur",
        "sorğu limiti — bir azdan yenidən cəhd edin", "pulsuz", "ödənişli", "JARVIS icazə istəyir", "İcazə verilsin?",
        "Bu kompüterdə əmr icra et", "Fayla yaz", "Faylı sil", "Ekranı çək", "Faylı söhbətə oxu",
        "Layihə kodunu süni intellekt təminatçısına göndər", "Layihənin testlərini işə sal", "Şəbəkədən nəsə yüklə",
        "Agentin bu planı icra etməsinə icazə ver", "Aşağı", "Orta", "Yüksək", "Maksimum", "Hipersürət", "Təhlükəsizlik",
        "Yeniləmə var", "Sizdə olan", "Yüklənir...", "Şəkil yaratma", "Ölçü:", "Keyfiyyət:", "Yaradılan şəkil burada görünəcək",
        "JARVIS-dən istədiyinizi soruşun... (şəkil üçün /image təsvir)", "Windows ayarını dəyiş", "Əlsiz rejim"]),
}

# 9.0: the Design page's sidebar button, appended to every table in KEYS order.
KEYS.append("Design")
for _code, _word in {"de": "Design", "es": "Diseño", "fr": "Design", "pt": "Design", "ru": "Дизайн",
                     "az": "Dizayn"}.items():
    TABLES[_code][2].append(_word)


def merge(languages: dict, strings: dict, answer_in: dict) -> None:
    for code, (name, instruction, values) in TABLES.items():
        languages[code] = name
        strings[code] = dict(zip(KEYS, values))
        answer_in[code] = instruction
    strings.setdefault("tr", {}).update({"Change a Windows setting": "Bir Windows ayarını değiştir", "Hands-free": "Eller serbest",
                                         "Design": "Tasarım"})
