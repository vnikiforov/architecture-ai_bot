import json
import os
import argparse
from pathlib import Path
import re

def validate_substitutions(substitutions):
    """
    Проверяет корректность подстановок:
    Соответствие регистра первой буквы
    """
    issues = []
    
    for old_str, new_str in substitutions.items():
        if not old_str or not new_str:
            continue
        
        # Проверяем первую букву (если она есть)
        old_first_char = old_str[0]
        new_first_char = new_str[0]
        
        # Определяем, является ли первая буква старой строки заглавной
        old_is_upper = old_first_char.isupper()
        new_is_upper = new_first_char.isupper()
        
        # Если первая буква старой строки заглавная, новая тоже должна быть заглавной
        if old_is_upper and not new_is_upper:
            issues.append(f"'{old_str}' -> '{new_str}' (должно быть: '{new_str[0].upper() + new_str[1:]}')")
        
        # Если первая буква старой строки строчная, новая тоже должна быть строчной
        if not old_is_upper and new_is_upper:
            # Но только если это действительно буква (не символ)
            if old_first_char.isalpha():
                issues.append(f"'{old_str}' -> '{new_str}' (должно быть: '{new_str[0].lower() + new_str[1:]}')")
    
    return issues

def categorize_substitutions(substitutions):
    """
    Разделяет подстановки на два типа:
    1. Многословные словосочетания (2+ слова)
    2. Отдельные слова (1 слово)
    """
    multiword_subs = {}
    singleword_subs = {}
    
    for old_str, new_str in substitutions.items():
        # Считаем количество слов (разделитель - пробел)
        word_count = len(old_str.strip().split())
        
        if word_count >= 2:
            multiword_subs[old_str] = new_str
        else:
            singleword_subs[old_str] = new_str
    
    return multiword_subs, singleword_subs

def scan_for_unused_patterns(directory, substitutions, extensions=None):
    """
    Сканирует файлы и возвращает список неиспользуемых шаблонов
    """
    if extensions:
        extensions = [ext.lower() if ext.startswith('.') else f'.{ext.lower()}' for ext in extensions]
    
    # Создаем множество для отслеживания найденных шаблонов
    found_patterns = set()
    
    # Функция для проверки содержимого файла
    def check_file_content(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Проверяем каждый шаблон
            for pattern in substitutions.keys():
                if pattern not in found_patterns:
                    # Ищем прямое вхождение
                    if pattern in content:
                        found_patterns.add(pattern)
                    # Ищем в одинарных кавычках
                    elif f"'{pattern}'" in content:
                        found_patterns.add(pattern)
                    # Ищем в двойных кавычках
                    elif f'"{pattern}"' in content:
                        found_patterns.add(pattern)
                    
                    # Если нашли все шаблоны, прекращаем поиск
                    if len(found_patterns) == len(substitutions):
                        return True  # Все шаблоны найдены
            
            return False
        except:
            return False
    
    # Рекурсивно обходим все файлы
    for root, dirs, files in os.walk(directory):
        for file in files:
            file_path = Path(root) / file
            
            if extensions:
                if file_path.suffix.lower() not in extensions:
                    continue
            
            # Пропускаем сам файл подстановок
            if str(file_path).endswith('.json'):
                continue
            
            # Проверяем файл
            if check_file_content(file_path):
                # Все шаблоны найдены, прекращаем поиск
                break
        else:
            continue
        break
    
    # Определяем неиспользованные шаблоны
    all_patterns = set(substitutions.keys())
    unused_patterns = all_patterns - found_patterns
    
    return unused_patterns

def load_and_validate_substitutions(json_file):
    """
    Загружает и валидирует словарь подстановок
    """
    with open(json_file, 'r', encoding='utf-8') as f:
        substitutions = json.load(f)
    
    # Преобразуем все ключи и значения в строки
    substitutions = {str(k): str(v) for k, v in substitutions.items()}
    
    # Выполняем проверки
    validation_issues = validate_substitutions(substitutions)
    
    if validation_issues:
        print("=" * 80)
        print("ОШИБКИ В ФАЙЛЕ ПОДСТАНОВОК (регистр первой буквы не соответствует):")
        print("=" * 80)
        for i, issue in enumerate(validation_issues, 1):
            print(f"{i}. {issue}")
        print("=" * 80)
        print(f"Всего ошибок: {len(validation_issues)}")
        return None, validation_issues, None
    
    return substitutions, [], None

def replace_quoted_content(content, substitutions, pass_num):
    """
    Заменяет текст внутри одинарных и двойных кавычек с учетом номера прохода
    """
    # Регулярные выражения для нахождения текста в кавычках
    single_quote_pattern = r"'([^']*)'"
    double_quote_pattern = r'"([^"]*)"'
    
    # Функция для замены внутри найденных совпадений
    def replace_in_match(match):
        text = match.group(1)  # Текст внутри кавычек
        original = match.group(0)  # Полное совпадение с кавычками
        
        # Проверяем каждую подстановку
        for old_str, new_str in substitutions.items():
            # Если текст полностью совпадает с тем, что нужно заменить
            if text == old_str:
                # Сохраняем тип кавычек
                quote_char = original[0]
                return f"{quote_char}{new_str}{quote_char}"
        
        return original
    
    # Применяем замены к тексту в одинарных кавычках
    content = re.sub(single_quote_pattern, replace_in_match, content)
    # Применяем замены к тексту в двойных кавычках
    content = re.sub(double_quote_pattern, replace_in_match, content)
    
    return content

def replace_in_file_two_pass(file_path, multiword_subs, singleword_subs, quotes_only=False):
    """
    Заменяет строки в два прохода:
    1. Сначала многословные словосочетания
    2. Затем отдельные слова
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        
        if quotes_only:
            # Проход 1: Заменяем многословные словосочетания в кавычках
            content = replace_quoted_content(content, multiword_subs, pass_num=1)
            # Проход 2: Заменяем отдельные слова в кавычках
            content = replace_quoted_content(content, singleword_subs, pass_num=2)
        else:
            # Проход 1: Заменяем многословные словосочетания везде
            for old_str, new_str in multiword_subs.items():
                content = content.replace(old_str, new_str)
            
            # Также заменяем многословные словосочетания в кавычках
            content = replace_quoted_content(content, multiword_subs, pass_num=1)
            
            # Проход 2: Заменяем отдельные слова везде
            for old_str, new_str in singleword_subs.items():
                content = content.replace(old_str, new_str)
            
            # Также заменяем отдельные слова в кавычках
            content = replace_quoted_content(content, singleword_subs, pass_num=2)
        
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        return False
    except Exception as e:
        print(f"Ошибка при обработке файла {file_path}: {e}")
        return False

def process_directory_two_pass(directory, multiword_subs, singleword_subs, extensions=None, quotes_only=False):
    """
    Обрабатывает все файлы в директории и поддиректориях в два прохода
    """
    if extensions:
        extensions = [ext.lower() if ext.startswith('.') else f'.{ext.lower()}' for ext in extensions]
    
    changed_files = 0
    total_files = 0
    
    for root, dirs, files in os.walk(directory):
        for file in files:
            file_path = Path(root) / file
            
            # Пропускаем сам файл подстановок
            if str(file_path).endswith('.json'):
                continue
            
            if extensions:
                if file_path.suffix.lower() not in extensions:
                    continue
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    f.read(1024)
            except:
                continue
            
            total_files += 1
            if replace_in_file_two_pass(file_path, multiword_subs, singleword_subs, quotes_only):
                changed_files += 1
                print(f"Изменен: {file_path}")
    
    return changed_files, total_files

def main():
    parser = argparse.ArgumentParser(
        description='Замена строк в текстовых файлах согласно JSON файлу подстановок (два прохода)'
    )
    parser.add_argument('directory', help='Директория для обработки')
    parser.add_argument('json_file', help='JSON файл с подстановками')
    parser.add_argument('--extensions', '-e', nargs='+', 
                       help='Расширения файлов для обработки (например: txt py js)')
    parser.add_argument('--dry-run', '-d', action='store_true',
                       help='Показать, что будет изменено, без внесения правок')
    parser.add_argument('--force', '-f', action='store_true',
                       help='Продолжить работу несмотря на предупреждения (не рекомендуется)')
    parser.add_argument('--quotes-only', '-q', action='store_true',
                       help='Заменять только текст в кавычках (по умолчанию заменяет везде)')
    
    args = parser.parse_args()
    
    # Проверяем существование директории и JSON файла
    if not os.path.isdir(args.directory):
        print(f"Ошибка: Директория '{args.directory}' не существует")
        return 1
    
    if not os.path.isfile(args.json_file):
        print(f"Ошибка: JSON файл '{args.json_file}' не существует")
        return 1
    
    # Загружаем и валидируем подстановки
    substitutions, issues, _ = load_and_validate_substitutions(args.json_file)
    
    if substitutions is None:
        if args.force:
            print("\nПРЕДУПРЕЖДЕНИЕ: работа продолжена принудительно, несмотря на ошибки!")
            # Загружаем без валидации
            with open(args.json_file, 'r', encoding='utf-8') as f:
                substitutions = json.load(f)
            substitutions = {str(k): str(v) for k, v in substitutions.items()}
        else:
            print("\nИсправьте ошибки в файле подстановок и повторите попытку.")
            return 1
    
    # Категоризируем подстановки
    multiword_subs, singleword_subs = categorize_substitutions(substitutions)
    
    print(f"\nАнализ подстановок:")
    print(f"Всего подстановок: {len(substitutions)}")
    print(f"Многословные словосочетания (сначала): {len(multiword_subs)}")
    print(f"Отдельные слова (потом): {len(singleword_subs)}")
    
    # Проверяем, есть ли неиспользуемые шаблоны
    unused_patterns = scan_for_unused_patterns(args.directory, substitutions, args.extensions)
    
    if unused_patterns:
        print("\n" + "=" * 80)
        print("ВНИМАНИЕ: найдены неиспользуемые значения 'было' в файле подстановок!")
        print("Каждое значение должно встретиться хотя бы один раз!")
        print("=" * 80)
        for i, pattern in enumerate(sorted(unused_patterns), 1):
            print(f"{i}. '{pattern}' -> '{substitutions[pattern]}'")
        print("=" * 80)
        print(f"Всего неиспользуемых значений: {len(unused_patterns)}")
        
        if not args.force:
            print("\nИсправьте файл подстановок и повторите попытку.")
            print("Или используйте --force для принудительного выполнения.")
            return 1
    
    # Выводим информацию о подстановках
    if issues and args.force:
        print("\nПРЕДУПРЕЖДЕНИЕ: работа продолжена принудительно, несмотря на ошибки!")
    
    # Показываем примеры замен
    print("\n" + "=" * 80)
    print("ПРИМЕРЫ ЗАМЕН (в два прохода):")
    print("=" * 80)
    
    # Пример с многословным словосочетанием и отдельным словом
    test_multiword = list(multiword_subs.items())[:2] if multiword_subs else []
    test_singleword = list(singleword_subs.items())[:2] if singleword_subs else []
    
    if test_multiword:
        print("\n1. МНОГОСЛОВНЫЕ СЛОВОСОЧЕТАНИЯ (заменяются первыми):")
        for old, new in test_multiword:
            print(f"   - '{old}' -> '{new}'")
            words = old.split()
            print(f"     Пример текста: Это {old} пример.")
            print(f"     После замены:  Это {new} пример.")
    
    if test_singleword:
        print("\n2. ОТДЕЛЬНЫЕ СЛОВА (заменяются после многословных):")
        for old, new in test_singleword:
            print(f"   - '{old}' -> '{new}'")
    
    # Пример комплексной замены
    if test_multiword and test_singleword:
        multi_old, multi_new = test_multiword[0]
        single_old, single_new = test_singleword[0]
        
        print(f"\n3. КОМПЛЕКСНЫЙ ПРИМЕР:")
        print(f"   Исходный текст: 'Это {multi_old} с {single_old} внутри'")
        
        # Проход 1: замена многословного
        after_pass1 = f"Это {multi_new} с {single_old} внутри"
        print(f"   После 1-го прохода: '{after_pass1}'")
        
        # Проход 2: замена отдельного слова
        after_pass2 = f"Это {multi_new} с {single_new} внутри"
        print(f"   После 2-го прохода: '{after_pass2}'")
    
    print("=" * 80)
    
    if args.dry_run:
        print(f"\nРежим предпросмотра (dry-run). Файлы не будут изменены.")
        print(f"Будут обработаны файлы в: {args.directory}")
        if args.extensions:
            print(f"Только с расширениями: {args.extensions}")
        if args.quotes_only:
            print(f"Заменять только текст в кавычках")
        
        print(f"\nПорядок замен:")
        print(f"  1. {len(multiword_subs)} многословных словосочетаний")
        print(f"  2. {len(singleword_subs)} отдельных слов")
        
        if unused_patterns:
            print(f"\nПРЕДУПРЕЖДЕНИЕ: {len(unused_patterns)} значений не будут использованы!")
        else:
            print("\nВсе значения из подстановок будут использованы.")
        
        return 0
    
    # Обрабатываем директорию
    print(f"\nОбработка директории: {args.directory}")
    if args.extensions:
        print(f"Только файлы с расширениями: {args.extensions}")
    if args.quotes_only:
        print(f"Заменять только текст в кавычках")
    
    print(f"\nЗапуск в два прохода:")
    print(f"  Проход 1: замена {len(multiword_subs)} многословных словосочетаний")
    print(f"  Проход 2: замена {len(singleword_subs)} отдельных слов")
    
    # Обрабатываем директорию в два прохода
    changed, total = process_directory_two_pass(args.directory, multiword_subs, singleword_subs, args.extensions, args.quotes_only)
    
    print(f"\nГотово!")
    print(f"Обработано файлов: {total}")
    print(f"Изменено файлов: {changed}")
    
    return 0

if __name__ == "__main__":
    exit(main())