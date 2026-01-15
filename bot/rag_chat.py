#!/usr/bin/env python3
"""
RAG-бот с:
- Релевантным поиском по ключевым словам
- Few-shot prompting (2 примера из базы)
- Chain-of-Thought (модель объясняет рассуждения)
- Защитой от ошибки 413 (контекст ≤ 8000 символов)
"""

import os
import sys
from pathlib import Path
import re
import httpx
from dotenv import load_dotenv


# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    print("❌ Ошибка: установите GROQ_API_KEY в .env")
    sys.exit(1)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL_NAME = "llama-3.1-8b-instant"

PROJECT_ROOT = Path(__file__).parent.parent
CHROMA_DB_PATH = PROJECT_ROOT / "indexing" / "chroma_db"
COLLECTION_NAME = "quantumforge_knowledge"


# ============================================================================
# ПОИСК ПО КЛЮЧЕВЫМ СЛОВАМ
# ============================================================================

def _extract_words(text: str) -> set:
    """Извлекает слова (только буквы), приводит к нижнему регистру"""
    return set(re.findall(r'[а-яёa-z]+', text.lower()))


def select_few_shot_examples(documents: list, max_examples: int = 2, max_len: int = 500) -> str:
    """Выбирает короткие, информативные чанки для few-shot"""
    examples = []
    for doc in documents:
        text = doc.strip()
        if (
            text and
            len(text) <= max_len and
            len(text.split()) >= 3 and  # не слишком коротко
            len(examples) < max_examples
        ):
            examples.append(text)
        if len(examples) >= max_examples:
            break
    
    # Если не хватает — добавляем нейтральные заглушки
    while len(examples) < max_examples:
        examples.append(
            "Цифровой двойник — это виртуальная модель физического объекта."
            if len(examples) == 0 else
            "SCADA — система диспетчерского контроля и управления."
        )
    
    return "\n".join(f"Пример {i+1}: {ex}" for i, ex in enumerate(examples))


def select_relevant_context(documents: list, question: str, max_chars: int = 8000) -> str:
    """Возвращает наиболее релевантные чанки на основе совпадения слов"""
    query_words = _extract_words(question)
    
    if not query_words:
        # Fallback: первые чанки
        parts, total = [], 0
        for doc in documents:
            text = doc.strip()
            if not text:
                continue
            if total + len(text) > max_chars:
                break
            parts.append(text)
            total += len(text) + 1
        return "\n\n".join(parts)
    
    # Оцениваем релевантность
    scored = []
    for doc in documents:
        text = doc.strip()
        if not text:
            continue
        doc_words = _extract_words(text)
        score = len(query_words & doc_words)
        if score > 0:
            scored.append((score, text))
    
    # Сортируем по убыванию релевантности
    scored.sort(key=lambda x: x[0], reverse=True)
    
    # Набираем контекст
    parts, total = [], 0
    for _, text in scored:
        if total + len(text) > max_chars:
            break
        parts.append(text)
        total += len(text) + 1
    
    # Если ничего не найдено — fallback
    if not parts:
        parts, total = [], 0
        for doc in documents[:15]:  # первые 15 чанков
            text = doc.strip()
            if not text:
                continue
            if total + len(text) > max_chars:
                break
            parts.append(text)
            total += len(text) + 1
    
    return "\n\n".join(parts)


# ============================================================================
# ГЕНЕРАЦИЯ ОТВЕТА
# ============================================================================

def query_llm(few_shot: str, context: str, question: str) -> str:
    system_prompt = (
        "Ты — эксперт по предоставленной базе знаний. "
        "Следуй инструкциям строго:\n"
        "1. Внимательно изучи примеры и контекст.\n"
        "2. Применяй Chain-of-Thought: сначала проанализируй информацию, "
        "затем сделай логический вывод.\n"
        "3. Отвечай ТОЛЬКО на основе контекста.\n"
        "4. Если информации нет — напиши: «Нет информации в базе знаний»."
    )

    user_prompt = (
        f"### Примеры:\n{few_shot}\n\n"
        f"### Контекст:\n{context}\n\n"
        f"### Вопрос:\n{question}\n\n"
        "### Пошаговое рассуждение и ответ:"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    json_data = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 400
    }

    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(GROQ_API_URL, headers=headers, json=json_data)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"❌ Ошибка LLM: {e}"


# ============================================================================
# ОСНОВНОЙ ЦИКЛ
# ============================================================================

def main():
    print("🧠 RAG-бот с релевантным поиском, Few-shot и CoT")
    print("   Загрузка базы знаний...", end="", flush=True)

    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
        collection = client.get_collection(name=COLLECTION_NAME)
        all_docs = collection.get(include=["documents"])["documents"]
        print(f" готово ({len(all_docs)} чанков).")
    except Exception as e:
        print(f"\n❌ Ошибка подключения к ChromaDB: {e}")
        sys.exit(1)

    # Подготавливаем few-shot один раз (можно кэшировать)
    few_shot = select_few_shot_examples(all_docs)
    print("   Few-shot примеры подготовлены.")

    print("\n✅ Бот готов. Задавайте вопросы (Ctrl+C для выхода).\n")

    while True:
        try:
            question = input("❓ Вопрос: ").strip()
            if not question:
                continue

            print("🔍 Поиск релевантных фрагментов...", end="", flush=True)
            context = select_relevant_context(all_docs, question, max_chars=8000)
            print(" готово.")

            print("🧠 Генерация ответа...", end="", flush=True)
            answer = query_llm(few_shot, context, question)
            print("\n\n💬 Ответ:\n")
            print(answer)
            print("\n" + "=" * 60)

        except KeyboardInterrupt:
            print("\n\n👋 До свидания!")
            break


if __name__ == "__main__":
    main()