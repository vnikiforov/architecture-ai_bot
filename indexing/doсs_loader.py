#!/usr/bin/env python3
"""
docs_loader.py - Загрузка и индексация текстовых документов для RAG-системы
Использует TF-IDF + SVD (scikit-learn) вместо нейросетевых эмбеддингов
Разбивает файлы на чанки по 10 слов
Все пути в отчётах — относительно этого скрипта (./indexing/)
"""

import os
import sys
from pathlib import Path
import time
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================

KNOWLEDGE_BASE_PATH = Path(__file__).parent.parent / "knowledge_base"
CHROMA_DB_PATH = Path(__file__).parent / "chroma_db"
COLLECTION_NAME = "quantumforge_knowledge"
MAX_FILES_TO_PROCESS = None
EMBEDDING_DIM = 300
CHUNK_SIZE_WORDS = 10  # размер чанка в словах


# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================

def chunk_text_by_words(text: str, chunk_size: int = 10) -> List[str]:
    """Разбивает текст на чанки по N слов"""
    if not text.strip():
        return []
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size):
        chunk = " ".join(words[i:i + chunk_size])
        if chunk.strip():
            chunks.append(chunk)
    return chunks


def make_relative(path: Path) -> str:
    """Преобразует путь в относительный от директории скрипта (./indexing/)"""
    try:
        return str(Path(path).relative_to(Path(__file__).parent))
    except ValueError:
        return str(path)


# ============================================================================
# EMBEDDING FUNCTION (совместима с ChromaDB >=0.5)
# ============================================================================

class TfidfEmbeddingFunction:
    def __init__(self, dim=300):
        self.dim = dim
        self.vectorizer = None
        self.svd = None
        self.is_fitted = False

    def fit(self, texts: List[str]):
        print("  📊 Обучение TF-IDF векторизатора...")
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.decomposition import TruncatedSVD
        
        self.vectorizer = TfidfVectorizer(
            max_features=5000,
            stop_words=None,
            lowercase=True,
            ngram_range=(1, 2)
        )
        tfidf_matrix = self.vectorizer.fit_transform(texts)
        
        actual_dim = min(self.dim, tfidf_matrix.shape[1] - 1)
        if actual_dim <= 0:
            actual_dim = 1
        print("  📉 Применение SVD для снижения размерности до {}...".format(actual_dim))
        self.svd = TruncatedSVD(n_components=actual_dim)
        self.svd.fit(tfidf_matrix)
        self.is_fitted = True
        print("  ✅ Векторизатор готов")

    def embed_documents(self, documents: List[str]) -> List[List[float]]:
        if not self.is_fitted:
            raise RuntimeError("Сначала вызовите .fit() на корпусе текстов!")
        tfidf = self.vectorizer.transform(documents)
        reduced = self.svd.transform(tfidf)
        return reduced.tolist()

    def embed_query(self, query: str) -> List[float]:
        if not self.is_fitted:
            raise RuntimeError("Сначала вызовите .fit() на корпусе текстов!")
        tfidf = self.vectorizer.transform([query])
        reduced = self.svd.transform(tfidf)
        return reduced[0].tolist()

    def name(self) -> str:
        return "tfidf-svd-embedding"


# ============================================================================
# ОСНОВНЫЕ ФУНКЦИИ
# ============================================================================

def print_header():
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    kb_rel = make_relative(KNOWLEDGE_BASE_PATH)
    db_rel = make_relative(CHROMA_DB_PATH)
    max_files = str(MAX_FILES_TO_PROCESS or 'все')

    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 22 + "ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ RAG" + " " * 22 + "║")
    print("╠" + "═" * 68 + "╣")
    print("║ Время запуска: {:<48} ║".format(now_str))
    print("║ Директория скрипта: .{:<37} ║".format(""))
    print("╠" + "─" * 68 + "╣")
    print("║ 📁 База знаний:   {:<40} ║".format(kb_rel))
    print("║ 💾 Векторная БД:  {:<40} ║".format(db_rel))
    print("║ 🧠 Модель:        TF-IDF + SVD (dim={}){:<28} ║".format(EMBEDDING_DIM, ""))
    print("║ 📏 Чанк:          {} слов{:<38} ║".format(CHUNK_SIZE_WORDS, ""))
    print("║ 📊 Макс. файлов:  {:<40} ║".format(max_files))
    print("╚" + "═" * 68 + "╝")
    print()


def check_dependencies():
    print("🔍 Проверка зависимостей...")
    
    required_packages = [
        ("chromadb", "pip install chromadb"),
        ("sklearn", "pip install scikit-learn"),
    ]
    
    all_ok = True
    for package, install_cmd in required_packages:
        try:
            if package == "chromadb":
                import chromadb
                print("  ✅ {:20} {}".format(package, chromadb.__version__))
            elif package == "sklearn":
                import sklearn
                print("  ✅ {:20} {}".format("scikit-learn", sklearn.__version__))
        except ImportError:
            print("  ❌ {:20} не установлен".format(package))
            print("     Установите: {}".format(install_cmd))
            all_ok = False
    
    return all_ok


def validate_paths():
    print("📁 Проверка структуры каталогов...")
    
    if not KNOWLEDGE_BASE_PATH.exists():
        rel_path = make_relative(KNOWLEDGE_BASE_PATH)
        print("  ❌ Каталог не найден: {}".format(rel_path))
        return False
    
    rel_path = make_relative(KNOWLEDGE_BASE_PATH)
    print("  ✅ Каталог базы знаний: {}".format(rel_path))
    
    txt_files = list(KNOWLEDGE_BASE_PATH.rglob("*.txt"))
    if not txt_files:
        print("  ⚠️  В каталоге нет .txt файлов")
        return False
    
    print("  ✅ Найдено .txt файлов: {}".format(len(txt_files)))
    
    try:
        CHROMA_DB_PATH.mkdir(parents=True, exist_ok=True)
        db_rel = make_relative(CHROMA_DB_PATH)
        print("  ✅ Каталог для БД: {}".format(db_rel))
    except Exception as e:
        print("  ❌ Не удалось создать каталог: {}".format(e))
        return False
    
    return True


def load_text_files():
    print("\n📥 Загрузка и чанкинг текстовых файлов из {}...".format(make_relative(KNOWLEDGE_BASE_PATH)))
    
    txt_files = list(KNOWLEDGE_BASE_PATH.rglob("*.txt"))
    
    if MAX_FILES_TO_PROCESS and MAX_FILES_TO_PROCESS > 0:
        txt_files = txt_files[:MAX_FILES_TO_PROCESS]
        print("  ⚙️  Ограничение: обрабатываю первые {} файлов".format(MAX_FILES_TO_PROCESS))
    
    total_files = len(txt_files)
    print("  📊 Всего файлов для обработки: {}".format(total_files))
    
    all_texts = []
    all_metadatas = []
    all_ids = []
    loaded_files = 0
    total_chunks = 0
    errors = 0
    total_chars = 0
    
    for idx, file_path in enumerate(txt_files, 1):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            
            if len(content) < 10:
                print("  ⚠️  [{:3d}/{}] Пропущен (слишком короткий): {}".format(idx, total_files, file_path.name))
                continue
            
            chunks = chunk_text_by_words(content, CHUNK_SIZE_WORDS)
            if not chunks:
                print("  ⚠️  [{:3d}/{}] Нет чанков после разбивки: {}".format(idx, total_files, file_path.name))
                continue
            
            loaded_files += 1
            total_chunks += len(chunks)
            
            file_rel_path = make_relative(file_path)
            stat = file_path.stat()
            
            for chunk_idx, chunk in enumerate(chunks):
                all_texts.append(chunk)
                metadata = {
                    "source": file_rel_path,
                    "filename": file_path.name,
                    "filepath": file_rel_path,
                    "relative_path": str(file_path.relative_to(KNOWLEDGE_BASE_PATH)),
                    "file_size": stat.st_size,
                    "content_length": len(chunk),
                    "last_modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "file_type": "text/plain",
                    "chunk_index": chunk_idx,
                    "total_chunks": len(chunks),
                    "chunk_size_words": CHUNK_SIZE_WORDS,
                }
                all_metadatas.append(metadata)
                
                doc_id = "doc_{:04d}_{}_ch{:03d}".format(idx, file_path.stem[:15], chunk_idx)
                all_ids.append(doc_id)
                total_chars += len(chunk)
            
            if idx % 10 == 0 or idx == total_files:
                progress = (idx / total_files) * 100
                print("  📈 [{:3d}/{}] {:5.1f}% | Файлов: {} | Чанков: {}".format(
                    idx, total_files, progress, loaded_files, total_chunks))
                
        except UnicodeDecodeError:
            errors += 1
            print("  ❌ [{:3d}/{}] Ошибка UTF-8: {}".format(idx, total_files, file_path.name))
        except Exception as e:
            errors += 1
            print("  ❌ [{:3d}/{}] Ошибка: {} - {}".format(idx, total_files, file_path.name, str(e)[:50]))
    
    print("\n  📊 ИТОГ ЗАГРУЗКИ:")
    print("     Успешно: {} файлов".format(loaded_files))
    print("     Чанков:  {} чанков".format(total_chunks))
    print("     Ошибки:  {} файлов".format(errors))
    
    if total_chunks == 0:
        raise ValueError("Не удалось создать ни одного чанка")
    
    avg_chars = total_chars // total_chunks
    print("     Общий объем: {:,} символов".format(total_chars))
    print("     Средний размер чанка: {:,} символов".format(avg_chars))
    
    return all_texts, all_metadatas, all_ids


def create_vector_database(texts, metadatas, ids):
    print("\n💾 Создание векторной базы данных...")
    print("  Путь: {}".format(make_relative(CHROMA_DB_PATH)))
    print("  Коллекция: {}".format(COLLECTION_NAME))
    
    try:
        import chromadb
        
        embed_fn = TfidfEmbeddingFunction(dim=EMBEDDING_DIM)
        embed_fn.fit(texts)
        
        print("  🧠 Генерация эмбеддингов для {} чанков...".format(len(texts)))
        embeddings = embed_fn.embed_documents(texts)
        print("  ✅ Эмбеддинги созданы")
        
        client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
        print("  ✅ Клиент ChromaDB создан")
        
        try:
            client.delete_collection(COLLECTION_NAME)
            print("  ⚠️  Удалена старая коллекция")
        except:
            pass
        
        collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={
                "created": datetime.now().isoformat(),
                "embedding_type": "tfidf-svd",
                "dim": EMBEDDING_DIM,
                "chunk_size_words": CHUNK_SIZE_WORDS,
                "source": make_relative(KNOWLEDGE_BASE_PATH),
                "total_chunks": len(texts),
                "description": "База знаний QuantumForge Software (TF-IDF, чанки)"
            }
        )
        print("  ✅ Коллекция создана")
        
        total_docs = len(texts)
        batch_size = 25
        print("\n  📤 Добавление чанков с эмбеддингами...")
        print("     Всего чанков: {}".format(total_docs))
        print("     Размер пачки: {}".format(batch_size))
        
        start_time = time.time()
        
        for i in range(0, total_docs, batch_size):
            batch_end = min(i + batch_size, total_docs)
            try:
                collection.add(
                    ids=ids[i:batch_end],
                    documents=texts[i:batch_end],
                    metadatas=metadatas[i:batch_end],
                    embeddings=embeddings[i:batch_end]
                )
                
                progress = (batch_end / total_docs) * 100
                elapsed = time.time() - start_time
                docs_per_sec = batch_end / elapsed if elapsed > 0 else 0
                
                print("     ✅ Пачка {:4d}-{:4d}: {:5.1f}% | {:.1f} чанков/сек".format(
                    i, batch_end, progress, docs_per_sec))
                
                if batch_end < total_docs:
                    time.sleep(0.05)
                    
            except Exception as e:
                print("     ❌ Ошибка пачки {}-{}: {}".format(i, batch_end, str(e)[:60]))
        
        elapsed_total = time.time() - start_time
        final_count = collection.count()
        
        print("\n  📊 ИТОГ СОЗДАНИЯ БАЗЫ:")
        print("     Добавлено чанков: {}".format(final_count))
        print("     Общее время: {:.1f} сек".format(elapsed_total))
        print("     Скорость: {:.1f} чанков/сек".format(final_count / elapsed_total))
        
        collection._custom_embed_fn = embed_fn
        
        return collection
        
    except Exception as e:
        print("  ❌ Ошибка создания базы: {}".format(e))
        raise


def test_database_search(collection, queries=None):
    if queries is None:
        queries = [
            "Что такое цифровой двойник?",
            "SCADA система",
            "моделирование промышленных объектов",
            "база знаний документация",
            "микросервисы архитектура"
        ]
    
    if not hasattr(collection, '_custom_embed_fn'):
        print("  ⚠️  Нет embedding function для поиска")
        return
    
    embed_fn = collection._custom_embed_fn
    
    print("\n🔍 Тестирование поиска...")
    
    for i, query in enumerate(queries, 1):
        print("\n  {}".format("─" * 50))
        print("  ЗАПРОС {}: {}".format(i, query))
        print("  {}".format("─" * 50))
        
        try:
            start = time.time()
            query_embedding = embed_fn.embed_query(query)
            
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=3,
                include=["documents", "metadatas", "distances"]
            )
            search_time = (time.time() - start) * 1000
            
            if results['documents'][0]:
                print("  ⏱️  Время поиска: {:.0f} мс".format(search_time))
                print("  📊 Найдено: {} результатов".format(len(results['documents'][0])))
                
                for j, (doc, meta, dist) in enumerate(zip(
                    results['documents'][0],
                    results['metadatas'][0],
                    results['distances'][0]
                ), 1):
                    preview = doc[:120].replace('\n', ' ')
                    if len(doc) > 120:
                        preview += "..."
                    similarity = 1/(1+dist)
                    filename = meta.get('filename', 'N/A')
                    chunk_idx = meta.get('chunk_index', '?')
                    print("\n    📄 Результат {}:".format(j))
                    print("       📁 Файл: {} (чанк {})".format(filename, chunk_idx))
                    print("       📐 Сходство: {:.3f}".format(similarity))
                    print("       📝 Текст: {}".format(preview))
            else:
                print("  ⚠️  Результатов не найдено")
                
        except Exception as e:
            print("  ❌ Ошибка поиска: {}".format(str(e)[:60]))


def save_configuration_info(texts, collection):
    info_file = Path(__file__).parent / "db_configuration.txt"
    
    kb_rel = make_relative(KNOWLEDGE_BASE_PATH)
    db_rel = make_relative(CHROMA_DB_PATH)
    
    info_content = (
        "{line}\n"
        "КОНФИГУРАЦИЯ ВЕКТОРНОЙ БАЗЫ ДАННЫХ (TF-IDF)\n"
        "{line}\n\n"
        "Дата создания: {created}\n\n"
        "ПУТИ (относительно скрипта):\n"
        "├── Исходные тексты: {kb_rel}\n"
        "├── Векторная БД:    {db_rel}\n"
        "└── Скрипт:         ./docs_loader.py\n\n"
        "ПАРАМЕТРЫ:\n"
        "├── Коллекция:        {collection}\n"
        "├── Тип эмбеддинга:   TF-IDF + SVD\n"
        "├── Размерность:      {dim}\n"
        "├── Размер чанка:     {chunk_size} слов\n"
        "└── Чанков в индексе: {num_chunks}\n\n"
        "ЗАВИСИМОСТИ:\n"
        "├── chromadb\n"
        "└── scikit-learn\n\n"
        "ИСПОЛЬЗОВАНИЕ В КОДЕ:\n"
        "```python\n"
        "import chromadb\n"
        "client = chromadb.PersistentClient(path=\"{db_rel}\")\n"
        "collection = client.get_collection(name=\"{collection}\")\n"
        "# Для поиска нужно самому генерировать эмбеддинги!\n"
        "```\n\n"
        "ПРИМЕЧАНИЯ:\n"
        "• Все файлы разбиты на чанки по {chunk_size} слов\n"
        "• Работает без GPU и без torch\n"
        "• Подходит для учебных проектов\n"
        "{line}"
    ).format(
        line="="*70,
        created=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        kb_rel=kb_rel,
        db_rel=db_rel,
        collection=COLLECTION_NAME,
        dim=EMBEDDING_DIM,
        chunk_size=CHUNK_SIZE_WORDS,
        num_chunks=len(texts)
    )
    
    try:
        with open(info_file, 'w', encoding='utf-8') as f:
            f.write(info_content.strip())
        print("\n📄 Конфигурация сохранена: {}".format(make_relative(info_file)))
    except Exception as e:
        print("\n⚠️  Не удалось сохранить конфигурацию: {}".format(e))


def main():
    print_header()

    if not check_dependencies():
        print("\n❌ Установите недостающие зависимости")
        sys.exit(1)

    if not validate_paths():
        print("\n❌ Проверьте структуру каталогов")
        sys.exit(1)

    try:
        print("\n" + "=" * 70)
        print("ЭТАП 1: ЗАГРУЗКА И ЧАНКИНГ ТЕКСТОВ")
        print("=" * 70)
        texts, metadatas, ids = load_text_files()
        
        print("\n" + "=" * 70)
        print("ЭТАП 2: СОЗДАНИЕ ВЕКТОРНОЙ БАЗЫ ДАННЫХ")
        print("=" * 70)
        collection = create_vector_database(texts, metadatas, ids)
        
        print("\n" + "=" * 70)
        print("ЭТАП 3: ТЕСТИРОВАНИЕ ПОИСКА")
        print("=" * 70)
        test_database_search(collection)
        
        print("\n" + "=" * 70)
        print("ЭТАП 4: СОХРАНЕНИЕ КОНФИГУРАЦИИ")
        print("=" * 70)
        save_configuration_info(texts, collection)
        
        print("\n" + "=" * 70)
        print("✅ ИНИЦИАЛИЗАЦИЯ УСПЕШНО ЗАВЕРШЕНА!")
        print("=" * 70)
        print("\n📊 РЕЗУЛЬТАТ:")
        print("   📁 Обработано файлов: {}".format(len(set(m['filename'] for m in metadatas))))
        print("   🧩 Чанков в индексе: {}".format(len(texts)))
        print("   💾 База данных: {}".format(make_relative(CHROMA_DB_PATH)))
        print("   📄 Конфигурация: {}".format(make_relative(Path(__file__).parent / "db_configuration.txt")))
        print("\n🚀 База данных готова к использованию в RAG-системе!")
    
    except ValueError as e:
        print("\n❌ ОШИБКА: {}".format(e))
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Прервано пользователем")
        sys.exit(0)
    except Exception as e:
        print("\n❌ НЕИЗВЕСТНАЯ ОШИБКА: {}: {}".format(type(e).__name__, e))
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()