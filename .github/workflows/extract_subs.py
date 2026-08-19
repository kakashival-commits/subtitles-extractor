name: Extract Subtitles

on:
  workflow_dispatch: # Дозволяє запуск вручну з сайту GitHub
  repository_dispatch:
    types: [start_subtitle_extraction] # Запуск по сигналу від Telegram-бота

jobs:
  extract:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout репозиторію
        uses: actions/checkout@v4

      - name: Встановлення інструментів
        run: |
          sudo apt-get update
          sudo apt-get install -y mkvtoolnix rclone python3-pip

      - name: Налаштування rclone для Google Drive
        run: |
          mkdir -p ~/.config/rclone
          echo "${{ secrets.RCLONE_CONFIG }}" > ~/.config/rclone/rclone.conf

      - name: Монтування Google Диску
        run: |
          mkdir -p /mnt/gdrive
          rclone mount gdrive: /mnt/gdrive --vfs-cache-mode writes --daemon
          sleep 5

      - name: Запуск Python-скрипта витягування
        run: |
          python3 extract_subs.py

      - name: Сповіщення у Telegram про завершення
        if: always()
        run: |
          curl -s -X POST "https://api.telegram.org/bot${{ secrets.TELEGRAM_BOT_TOKEN }}/sendMessage" \
            -d "chat_id=${{ secrets.TELEGRAM_CHAT_ID }}" \
            -d "text=✅ GitHub Actions: Обробку субтитрів на Google Диску завершено!"
