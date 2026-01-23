"""
Telegram Work Analyzer
Анализирует чаты за последний месяц и генерирует:
- SOP документы для делегирования
- Рекомендации по оптимизации
- Метрики использования времени
"""

import asyncio
import json
import os
from datetime import datetime, timedelta
from collections import defaultdict
from telethon import TelegramClient
from telethon.tl.types import User, Chat, Channel
import anthropic

# === КОНФИГУРАЦИЯ ===
API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
SESSION_NAME = "work_analyzer_session"

# Период анализа
DAYS_TO_ANALYZE = 30

# Лимиты
MAX_MESSAGES_PER_CHAT = 500
MAX_CHATS = 50


class TelegramWorkAnalyzer:
    def __init__(self):
        self.client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
        self.anthropic = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.my_id = None
        self.data = {
            "chats": {},
            "my_messages": [],
            "stats": defaultdict(int)
        }
    
    async def connect(self):
        """Подключение к Telegram"""
        await self.client.start()
        me = await self.client.get_me()
        self.my_id = me.id
        print(f"✅ Подключен как: {me.first_name} (@{me.username})")
    
    async def collect_messages(self):
        """Сбор сообщений за последний месяц"""
        cutoff_date = datetime.now() - timedelta(days=DAYS_TO_ANALYZE)
        
        print(f"\n📥 Собираю сообщения с {cutoff_date.strftime('%d.%m.%Y')}...")
        
        dialogs = await self.client.get_dialogs(limit=MAX_CHATS)
        
        for dialog in dialogs:
            entity = dialog.entity
            chat_name = self._get_chat_name(entity)
            chat_type = self._get_chat_type(entity)
            
            # Пропускаем ботов и каналы без комментариев
            if chat_type == "bot":
                continue
            
            print(f"  📂 {chat_name} ({chat_type})...", end=" ")
            
            messages = []
            my_messages_count = 0
            
            async for msg in self.client.iter_messages(
                entity, 
                limit=MAX_MESSAGES_PER_CHAT,
                offset_date=datetime.now()
            ):
                if msg.date.replace(tzinfo=None) < cutoff_date:
                    break
                
                if msg.text:
                    msg_data = {
                        "date": msg.date.isoformat(),
                        "text": msg.text[:1000],  # Обрезаем длинные
                        "is_mine": msg.sender_id == self.my_id,
                        "hour": msg.date.hour
                    }
                    messages.append(msg_data)
                    
                    if msg.sender_id == self.my_id:
                        my_messages_count += 1
                        self.data["my_messages"].append({
                            "chat": chat_name,
                            "chat_type": chat_type,
                            **msg_data
                        })
            
            if messages:
                self.data["chats"][chat_name] = {
                    "type": chat_type,
                    "total_messages": len(messages),
                    "my_messages": my_messages_count,
                    "messages": messages
                }
                print(f"{len(messages)} сообщений ({my_messages_count} моих)")
            else:
                print("пусто")
        
        self._calculate_stats()
        print(f"\n✅ Собрано: {len(self.data['my_messages'])} твоих сообщений в {len(self.data['chats'])} чатах")
    
    def _get_chat_name(self, entity):
        """Получить название чата"""
        if isinstance(entity, User):
            name = entity.first_name or ""
            if entity.last_name:
                name += f" {entity.last_name}"
            return name.strip() or f"User_{entity.id}"
        return getattr(entity, 'title', f"Chat_{entity.id}")
    
    def _get_chat_type(self, entity):
        """Определить тип чата"""
        if isinstance(entity, User):
            if entity.bot:
                return "bot"
            return "personal"
        elif isinstance(entity, Chat):
            return "group"
        elif isinstance(entity, Channel):
            if entity.megagroup:
                return "supergroup"
            return "channel"
        return "unknown"
    
    def _calculate_stats(self):
        """Подсчёт базовой статистики"""
        stats = self.data["stats"]
        
        for msg in self.data["my_messages"]:
            stats["total_my_messages"] += 1
            stats[f"type_{msg['chat_type']}"] += 1
            stats[f"hour_{msg['hour']}"] += 1
        
        # Топ чатов по моей активности
        chat_activity = {}
        for chat_name, chat_data in self.data["chats"].items():
            chat_activity[chat_name] = chat_data["my_messages"]
        
        stats["top_chats"] = dict(
            sorted(chat_activity.items(), key=lambda x: x[1], reverse=True)[:10]
        )
    
    def analyze_with_claude(self):
        """Анализ через Claude API"""
        print("\n🧠 Анализирую с помощью Claude...")
        
        # Подготовка данных для анализа
        analysis_data = self._prepare_analysis_data()
        
        prompt = f"""Ты — эксперт по продуктивности и бизнес-процессам. 
Проанализируй мою рабочую коммуникацию в Telegram за последний месяц.

## ДАННЫЕ ДЛЯ АНАЛИЗА

### Статистика
- Всего моих сообщений: {self.data['stats']['total_my_messages']}
- В личных чатах: {self.data['stats'].get('type_personal', 0)}
- В группах: {self.data['stats'].get('type_group', 0) + self.data['stats'].get('type_supergroup', 0)}

### Топ чатов по моей активности
{json.dumps(self.data['stats']['top_chats'], indent=2, ensure_ascii=False)}

### Распределение по часам
{self._format_hourly_stats()}

### Примеры моих сообщений (сгруппированы по чатам)
{analysis_data}

---

## ЗАДАЧА

Сгенерируй комплексный отчёт в формате JSON:

```json
{{
  "executive_summary": "Краткое резюме (3-4 предложения)",
  
  "time_analysis": {{
    "peak_hours": ["часы наибольшей активности"],
    "wasted_time_patterns": ["паттерны потери времени"],
    "recommendations": ["рекомендации по тайм-менеджменту"]
  }},
  
  "delegation_opportunities": [
    {{
      "task": "название задачи",
      "current_time_spent": "оценка времени",
      "can_delegate_to": "кому делегировать",
      "priority": "high/medium/low"
    }}
  ],
  
  "sop_candidates": [
    {{
      "process_name": "Название процесса",
      "description": "Что это за процесс",
      "steps": ["шаг 1", "шаг 2", "..."],
      "triggers": "когда запускается",
      "owner": "кто должен выполнять",
      "tools_needed": ["инструменты"]
    }}
  ],
  
  "communication_patterns": {{
    "repetitive_explanations": ["что объясняешь повторно"],
    "bottlenecks": ["где застревают процессы"],
    "improvements": ["как улучшить коммуникацию"]
  }},
  
  "automation_ideas": [
    {{
      "idea": "что автоматизировать",
      "impact": "high/medium/low",
      "implementation": "как реализовать"
    }}
  ],
  
  "metrics": {{
    "operational_vs_strategic": "X% / Y%",
    "response_time_estimate": "оценка",
    "context_switching": "оценка частоты переключений"
  }},
  
  "action_plan": [
    {{
      "action": "конкретное действие",
      "priority": 1,
      "expected_result": "ожидаемый результат"
    }}
  ]
}}
```

Будь конкретным. Называй реальные чаты и задачи из данных.
Фокусируйся на actionable insights, а не общих советах.
"""

        response = self.anthropic.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}]
        )
        
        return self._parse_claude_response(response.content[0].text)
    
    def _prepare_analysis_data(self):
        """Подготовка данных для Claude"""
        result = []
        
        for chat_name, chat_data in self.data["chats"].items():
            my_msgs = [m for m in chat_data["messages"] if m["is_mine"]]
            if not my_msgs:
                continue
            
            # Берём sample сообщений
            sample = my_msgs[:30] if len(my_msgs) > 30 else my_msgs
            
            result.append(f"\n### {chat_name} ({chat_data['type']}) — {len(my_msgs)} сообщений")
            for msg in sample:
                date = msg["date"][:10]
                result.append(f"[{date}] {msg['text'][:200]}")
        
        return "\n".join(result)[:50000]  # Лимит контекста
    
    def _format_hourly_stats(self):
        """Форматирование статистики по часам"""
        hours = {}
        for key, value in self.data["stats"].items():
            if key.startswith("hour_"):
                hour = int(key.split("_")[1])
                hours[hour] = value
        
        result = []
        for hour in sorted(hours.keys()):
            bar = "█" * (hours[hour] // 5)
            result.append(f"{hour:02d}:00 — {hours[hour]:3d} {bar}")
        
        return "\n".join(result)
    
    def _parse_claude_response(self, text):
        """Извлечение JSON из ответа Claude"""
        try:
            # Ищем JSON блок
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass
        
        return {"raw_response": text}
    
    def generate_reports(self, analysis):
        """Генерация отчётов"""
        print("\n📝 Генерирую отчёты...")
        
        # 1. Основной отчёт
        self._save_main_report(analysis)
        
        # 2. SOP документы
        self._save_sop_documents(analysis)
        
        # 3. Action план
        self._save_action_plan(analysis)
        
        # 4. Сырые данные
        self._save_raw_data()
        
        print("\n✅ Отчёты сохранены в папку 'reports/'")
    
    def _save_main_report(self, analysis):
        """Главный отчёт в Markdown"""
        os.makedirs("reports", exist_ok=True)
        
        report = f"""# 📊 Анализ рабочей коммуникации
**Период:** {DAYS_TO_ANALYZE} дней
**Дата отчёта:** {datetime.now().strftime('%d.%m.%Y %H:%M')}

---

## 📋 Резюме

{analysis.get('executive_summary', 'Нет данных')}

---

## ⏰ Анализ времени

### Пиковые часы активности
{self._format_list(analysis.get('time_analysis', {}).get('peak_hours', []))}

### Паттерны потери времени
{self._format_list(analysis.get('time_analysis', {}).get('wasted_time_patterns', []))}

### Рекомендации
{self._format_list(analysis.get('time_analysis', {}).get('recommendations', []))}

---

## 🎯 Возможности для делегирования

{self._format_delegation_table(analysis.get('delegation_opportunities', []))}

---

## 💬 Паттерны коммуникации

### Повторяющиеся объяснения (нужна документация)
{self._format_list(analysis.get('communication_patterns', {}).get('repetitive_explanations', []))}

### Узкие места (где застревают процессы)
{self._format_list(analysis.get('communication_patterns', {}).get('bottlenecks', []))}

### Как улучшить
{self._format_list(analysis.get('communication_patterns', {}).get('improvements', []))}

---

## 🤖 Идеи автоматизации

{self._format_automation_table(analysis.get('automation_ideas', []))}

---

## 📈 Метрики

| Метрика | Значение |
|---------|----------|
| Операционка vs Стратегия | {analysis.get('metrics', {}).get('operational_vs_strategic', 'N/A')} |
| Время ответа | {analysis.get('metrics', {}).get('response_time_estimate', 'N/A')} |
| Переключение контекста | {analysis.get('metrics', {}).get('context_switching', 'N/A')} |

---

## 📊 Статистика из данных

- **Всего сообщений:** {self.data['stats']['total_my_messages']}
- **Личные чаты:** {self.data['stats'].get('type_personal', 0)}
- **Группы:** {self.data['stats'].get('type_group', 0) + self.data['stats'].get('type_supergroup', 0)}

### Топ-10 чатов по активности
{self._format_top_chats()}

### Распределение по часам
```
{self._format_hourly_stats()}
```
"""
        
        with open("reports/main_report.md", "w", encoding="utf-8") as f:
            f.write(report)
        
        print("  ✓ reports/main_report.md")
    
    def _save_sop_documents(self, analysis):
        """Отдельные SOP документы"""
        sops = analysis.get("sop_candidates", [])
        
        if not sops:
            return
        
        os.makedirs("reports/sops", exist_ok=True)
        
        for i, sop in enumerate(sops, 1):
            filename = f"reports/sops/SOP_{i:02d}_{self._slugify(sop.get('process_name', 'process'))}.md"
            
            content = f"""# SOP: {sop.get('process_name', 'Без названия')}

## Описание
{sop.get('description', '')}

## Триггер
{sop.get('triggers', 'Не указан')}

## Ответственный
{sop.get('owner', 'Не назначен')}

## Необходимые инструменты
{self._format_list(sop.get('tools_needed', []))}

## Шаги выполнения

{self._format_numbered_list(sop.get('steps', []))}

---
*Создано автоматически: {datetime.now().strftime('%d.%m.%Y')}*
"""
            
            with open(filename, "w", encoding="utf-8") as f:
                f.write(content)
            
            print(f"  ✓ {filename}")
    
    def _save_action_plan(self, analysis):
        """Action план"""
        actions = analysis.get("action_plan", [])
        
        content = f"""# 🎯 Action Plan
**Дата:** {datetime.now().strftime('%d.%m.%Y')}

---

"""
        for action in actions:
            priority = action.get("priority", "?")
            content += f"""## [{priority}] {action.get('action', 'Действие')}

**Ожидаемый результат:** {action.get('expected_result', 'Не указан')}

---

"""
        
        with open("reports/action_plan.md", "w", encoding="utf-8") as f:
            f.write(content)
        
        print("  ✓ reports/action_plan.md")
    
    def _save_raw_data(self):
        """Сохранение сырых данных"""
        # Статистика без полных сообщений
        stats_only = {
            "stats": dict(self.data["stats"]),
            "chats_summary": {
                name: {
                    "type": data["type"],
                    "total": data["total_messages"],
                    "mine": data["my_messages"]
                }
                for name, data in self.data["chats"].items()
            }
        }
        
        with open("reports/stats.json", "w", encoding="utf-8") as f:
            json.dump(stats_only, f, ensure_ascii=False, indent=2)
        
        print("  ✓ reports/stats.json")
    
    # === Helpers ===
    
    def _format_list(self, items):
        if not items:
            return "*Нет данных*"
        return "\n".join(f"- {item}" for item in items)
    
    def _format_numbered_list(self, items):
        if not items:
            return "*Нет шагов*"
        return "\n".join(f"{i}. {item}" for i, item in enumerate(items, 1))
    
    def _format_delegation_table(self, items):
        if not items:
            return "*Нет данных*"
        
        result = "| Задача | Время | Кому делегировать | Приоритет |\n"
        result += "|--------|-------|-------------------|------------|\n"
        
        for item in items:
            result += f"| {item.get('task', '')} | {item.get('current_time_spent', '')} | {item.get('can_delegate_to', '')} | {item.get('priority', '')} |\n"
        
        return result
    
    def _format_automation_table(self, items):
        if not items:
            return "*Нет идей*"
        
        result = "| Идея | Импакт | Реализация |\n"
        result += "|------|--------|------------|\n"
        
        for item in items:
            result += f"| {item.get('idea', '')} | {item.get('impact', '')} | {item.get('implementation', '')} |\n"
        
        return result
    
    def _format_top_chats(self):
        top = self.data["stats"].get("top_chats", {})
        return "\n".join(f"- **{name}**: {count} сообщений" for name, count in top.items())
    
    def _slugify(self, text):
        import re
        text = text.lower().strip()
        text = re.sub(r'[^\w\s-]', '', text)
        text = re.sub(r'[\s_-]+', '_', text)
        return text[:50]
    
    async def run(self):
        """Основной запуск"""
        print("=" * 50)
        print("🔍 TELEGRAM WORK ANALYZER")
        print("=" * 50)
        
        await self.connect()
        await self.collect_messages()
        
        analysis = self.analyze_with_claude()
        self.generate_reports(analysis)
        
        # Сохраняем полный анализ
        with open("reports/full_analysis.json", "w", encoding="utf-8") as f:
            json.dump(analysis, f, ensure_ascii=False, indent=2)
        
        print("\n" + "=" * 50)
        print("✅ ГОТОВО!")
        print("=" * 50)
        print("\nОткрой reports/main_report.md для полного отчёта")
        print("SOP документы в reports/sops/")


async def main():
    analyzer = TelegramWorkAnalyzer()
    await analyzer.run()


if __name__ == "__main__":
    asyncio.run(main())
