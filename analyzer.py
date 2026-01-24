"""
Telegram Work Analyzer — Railway Edition
Анализирует чаты за последний месяц и отправляет отчёт через бота
"""

import asyncio
import json
import os
from datetime import datetime, timedelta
from collections import defaultdict
from telethon import TelegramClient
from telethon.tl.types import User, Chat, Channel
from telethon.sessions import StringSession
import anthropic
import httpx

# === КОНФИГУРАЦИЯ ===
# Используем твои имена переменных
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")  # Твоя переменная
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("MY_USER_ID", "")  # Твоя переменная

# Период анализа
DAYS_TO_ANALYZE = 30

# Лимиты
MAX_MESSAGES_PER_CHAT = 500
MAX_CHATS = 50


class TelegramWorkAnalyzer:
    def __init__(self):
        # Проверяем что все переменные есть
        if not API_ID or not API_HASH:
            raise ValueError("TELEGRAM_API_ID и TELEGRAM_API_HASH обязательны!")
        if not SESSION_STRING:
            raise ValueError("SESSION_STRING обязателен!")
        
        # Используем StringSession для serverless
        self.client = TelegramClient(
            StringSession(SESSION_STRING), 
            API_ID, 
            API_HASH
        )
        self.anthropic = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.my_id = None
        self.data = {
            "chats": {},
            "my_messages": [],
            "stats": defaultdict(int)
        }
    
    async def connect(self):
        """Подключение к Telegram"""
        # connect() вместо start() — сессия уже авторизована
        await self.client.connect()
        
        if not await self.client.is_user_authorized():
            raise ValueError("Session string невалидный! Перегенерируй через generate_session.py")
        
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
            
            if chat_type == "bot":
                continue
            
            print(f"  📂 {chat_name} ({chat_type})...", end=" ", flush=True)
            
            messages = []
            my_messages_count = 0
            
            try:
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
                            "text": msg.text[:1000],
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
            except Exception as e:
                print(f"ошибка: {e}")
                continue
            
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
        if isinstance(entity, User):
            name = entity.first_name or ""
            if entity.last_name:
                name += f" {entity.last_name}"
            return name.strip() or f"User_{entity.id}"
        return getattr(entity, 'title', f"Chat_{entity.id}")
    
    def _get_chat_type(self, entity):
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
        stats = self.data["stats"]
        
        for msg in self.data["my_messages"]:
            stats["total_my_messages"] += 1
            stats[f"type_{msg['chat_type']}"] += 1
            stats[f"hour_{msg['hour']}"] += 1
        
        chat_activity = {}
        for chat_name, chat_data in self.data["chats"].items():
            chat_activity[chat_name] = chat_data["my_messages"]
        
        stats["top_chats"] = dict(
            sorted(chat_activity.items(), key=lambda x: x[1], reverse=True)[:10]
        )
    
    def analyze_with_claude(self):
        """Анализ через Claude API"""
        print("\n🧠 Анализирую с помощью Claude...")
        
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
        result = []
        
        for chat_name, chat_data in self.data["chats"].items():
            my_msgs = [m for m in chat_data["messages"] if m["is_mine"]]
            if not my_msgs:
                continue
            
            sample = my_msgs[:30] if len(my_msgs) > 30 else my_msgs
            
            result.append(f"\n### {chat_name} ({chat_data['type']}) — {len(my_msgs)} сообщений")
            for msg in sample:
                date = msg["date"][:10]
                result.append(f"[{date}] {msg['text'][:200]}")
        
        return "\n".join(result)[:50000]
    
    def _format_hourly_stats(self):
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
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass
        
        return {"raw_response": text}
    
    def format_telegram_report(self, analysis):
        """Форматирование отчёта для Telegram"""
        
        # Главное сообщение
        main_report = f"""📊 <b>АНАЛИЗ КОММУНИКАЦИИ</b>
<i>Период: {DAYS_TO_ANALYZE} дней</i>

{analysis.get('executive_summary', 'Нет данных')}

━━━━━━━━━━━━━━━

📈 <b>СТАТИСТИКА</b>
• Всего сообщений: <code>{self.data['stats']['total_my_messages']}</code>
• Личные чаты: <code>{self.data['stats'].get('type_personal', 0)}</code>
• Группы: <code>{self.data['stats'].get('type_group', 0) + self.data['stats'].get('type_supergroup', 0)}</code>

━━━━━━━━━━━━━━━

⏰ <b>ВРЕМЯ</b>
Пики: {', '.join(analysis.get('time_analysis', {}).get('peak_hours', ['N/A'])[:3])}

Потери времени:
{self._format_tg_list(analysis.get('time_analysis', {}).get('wasted_time_patterns', [])[:3])}

━━━━━━━━━━━━━━━

📊 <b>МЕТРИКИ</b>
• Операционка/Стратегия: {analysis.get('metrics', {}).get('operational_vs_strategic', 'N/A')}
• Переключение контекста: {analysis.get('metrics', {}).get('context_switching', 'N/A')}
"""

        # Делегирование
        delegation = analysis.get('delegation_opportunities', [])
        delegation_msg = "🎯 <b>ДЕЛЕГИРОВАТЬ</b>\n\n"
        for item in delegation[:5]:
            priority_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(item.get('priority', ''), "⚪")
            delegation_msg += f"{priority_emoji} <b>{item.get('task', '')}</b>\n"
            delegation_msg += f"   → {item.get('can_delegate_to', 'не указано')}\n"
            delegation_msg += f"   ⏱ {item.get('current_time_spent', '')}\n\n"

        # SOP документы
        sops = analysis.get('sop_candidates', [])
        sop_messages = []
        for i, sop in enumerate(sops[:5], 1):
            sop_msg = f"""📋 <b>SOP #{i}: {sop.get('process_name', 'Процесс')}</b>

{sop.get('description', '')}

<b>Триггер:</b> {sop.get('triggers', 'не указан')}
<b>Владелец:</b> {sop.get('owner', 'не назначен')}

<b>Шаги:</b>
{self._format_tg_numbered(sop.get('steps', []))}

<b>Инструменты:</b> {', '.join(sop.get('tools_needed', []))}
"""
            sop_messages.append(sop_msg)

        # Action план
        actions = analysis.get('action_plan', [])
        action_msg = "🚀 <b>ACTION PLAN</b>\n\n"
        for item in actions[:7]:
            action_msg += f"<b>[{item.get('priority', '?')}]</b> {item.get('action', '')}\n"
            action_msg += f"    <i>→ {item.get('expected_result', '')}</i>\n\n"

        # Автоматизация
        automation = analysis.get('automation_ideas', [])
        auto_msg = "🤖 <b>АВТОМАТИЗИРОВАТЬ</b>\n\n"
        for item in automation[:5]:
            impact_emoji = {"high": "🔥", "medium": "⚡", "low": "💡"}.get(item.get('impact', ''), "💡")
            auto_msg += f"{impact_emoji} <b>{item.get('idea', '')}</b>\n"
            auto_msg += f"   <i>{item.get('implementation', '')}</i>\n\n"

        # Топ чатов
        top_chats = self.data['stats'].get('top_chats', {})
        top_msg = "💬 <b>ТОП-10 ЧАТОВ</b>\n\n"
        for name, count in list(top_chats.items())[:10]:
            top_msg += f"• <b>{name}</b>: {count}\n"

        return {
            "main": main_report,
            "delegation": delegation_msg,
            "sops": sop_messages,
            "actions": action_msg,
            "automation": auto_msg,
            "top_chats": top_msg
        }
    
    def _format_tg_list(self, items):
        if not items:
            return "• Нет данных"
        return "\n".join(f"• {item}" for item in items)
    
    def _format_tg_numbered(self, items):
        if not items:
            return "Нет шагов"
        return "\n".join(f"{i}. {item}" for i, item in enumerate(items, 1))
    
    async def send_via_bot(self, reports):
        """Отправка отчётов через бота"""
        print("\n📤 Отправляю отчёты через бота...")
        
        if not BOT_TOKEN or not CHAT_ID:
            print("⚠️ BOT_TOKEN или CHAT_ID не указаны — пропускаю отправку")
            return
        
        base_url = f"https://api.telegram.org/bot{BOT_TOKEN}"
        
        async with httpx.AsyncClient() as client:
            # Отправляем сообщения последовательно
            messages_to_send = [
                ("📊 Главный отчёт", reports["main"]),
                ("🎯 Делегирование", reports["delegation"]),
                ("🚀 Action Plan", reports["actions"]),
                ("🤖 Автоматизация", reports["automation"]),
                ("💬 Топ чатов", reports["top_chats"]),
            ]
            
            for title, text in messages_to_send:
                try:
                    resp = await client.post(
                        f"{base_url}/sendMessage",
                        json={
                            "chat_id": CHAT_ID,
                            "text": text[:4096],
                            "parse_mode": "HTML"
                        }
                    )
                    if resp.status_code == 200:
                        print(f"  ✓ {title}")
                    else:
                        print(f"  ✗ {title}: {resp.text}")
                    await asyncio.sleep(0.5)
                except Exception as e:
                    print(f"  ✗ {title}: {e}")
            
            # Отправляем SOP документы
            for i, sop_text in enumerate(reports["sops"], 1):
                try:
                    resp = await client.post(
                        f"{base_url}/sendMessage",
                        json={
                            "chat_id": CHAT_ID,
                            "text": sop_text[:4096],
                            "parse_mode": "HTML"
                        }
                    )
                    if resp.status_code == 200:
                        print(f"  ✓ SOP #{i}")
                    else:
                        print(f"  ✗ SOP #{i}: {resp.text}")
                    await asyncio.sleep(0.5)
                except Exception as e:
                    print(f"  ✗ SOP #{i}: {e}")
            
            # Финальное сообщение
            await client.post(
                f"{base_url}/sendMessage",
                json={
                    "chat_id": CHAT_ID,
                    "text": f"✅ <b>Анализ завершён</b>\n\n<i>{datetime.now().strftime('%d.%m.%Y %H:%M')}</i>",
                    "parse_mode": "HTML"
                }
            )
        
        print("✅ Все отчёты отправлены!")
    
    async def run(self):
        """Основной запуск"""
        print("=" * 50)
        print("🔍 TELEGRAM WORK ANALYZER")
        print(f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        print("=" * 50)
        
        try:
            await self.connect()
            await self.collect_messages()
            
            if self.data['stats']['total_my_messages'] == 0:
                print("⚠️ Нет сообщений для анализа")
                return
            
            analysis = self.analyze_with_claude()
            reports = self.format_telegram_report(analysis)
            await self.send_via_bot(reports)
            
            print("\n" + "=" * 50)
            print("✅ ГОТОВО!")
            print("=" * 50)
            
        except Exception as e:
            print(f"\n❌ Ошибка: {e}")
            import traceback
            traceback.print_exc()
            
            # Отправляем уведомление об ошибке
            if BOT_TOKEN and CHAT_ID:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                        json={
                            "chat_id": CHAT_ID,
                            "text": f"❌ <b>Ошибка анализатора</b>\n\n<code>{str(e)[:500]}</code>",
                            "parse_mode": "HTML"
                        }
                    )
        finally:
            await self.client.disconnect()


async def main():
    # Проверяем переменные перед запуском
    print("Проверяю конфигурацию...")
    print(f"  API_ID: {'✓' if API_ID else '✗'}")
    print(f"  API_HASH: {'✓' if API_HASH else '✗'}")
    print(f"  SESSION_STRING: {'✓' if SESSION_STRING else '✗'} ({len(SESSION_STRING)} chars)")
    print(f"  ANTHROPIC_API_KEY: {'✓' if ANTHROPIC_API_KEY else '✗'}")
    print(f"  BOT_TOKEN: {'✓' if BOT_TOKEN else '✗'}")
    print(f"  CHAT_ID: {'✓' if CHAT_ID else '✗'}")
    print()
    
    analyzer = TelegramWorkAnalyzer()
    await analyzer.run()


if __name__ == "__main__":
    asyncio.run(main())
