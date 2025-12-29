import json
import os
import argparse
from pathlib import Path

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
                if pattern not in found_patterns and pattern in content:
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

def replace_in_file(file_path, substitutions):
    """
    Заменяет строки в одном файле согласно словарю подстановок
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        for old_str, new_str in substitutions.items():
            content = content.replace(old_str, new_str)
        
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        return False
    except Exception as e:
        print(f"Ошибка при обработке файла {file_path}: {e}")
        return False

def process_directory(directory, substitutions, extensions=None):
    """
    Обрабатывает все файлы в директории и поддиректориях
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
            if replace_in_file(file_path, substitutions):
                changed_files += 1
                print(f"Изменен: {file_path}")
    
    return changed_files, total_files

def main():
    parser = argparse.ArgumentParser(
        description='Замена строк в текстовых файлах согласно JSON файлу подстановок'
    )
    parser.add_argument('directory', help='Директория для обработки')
    parser.add_argument('json_file', help='JSON файл с подстановками')
    parser.add_argument('--extensions', '-e', nargs='+', 
                       help='Расширения файлов для обработки (например: txt py js)')
    parser.add_argument('--dry-run', '-d', action='store_true',
                       help='Показать, что будет изменено, без внесения правок')
    parser.add_argument('--force', '-f', action='store_true',
                       help='Продолжить работу несмотря на предупреждения (не рекомендуется)')
    
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
        print("\nБудут применены следующие подстановки:")
        print("=" * 80)
        for old, new in substitutions.items():
            print(f"  '{old}' -> '{new}'")
        print("=" * 80)
    elif not issues:
        print(f"\nЗагружено {len(substitutions)} корректных подстановок")
        print("Подстановки:")
        print("=" * 80)
        for old, new in substitutions.items():
            print(f"  '{old}' -> '{new}'")
        print("=" * 80)
    
    if args.dry_run:
        print(f"\nРежим предпросмотра (dry-run). Файлы не будут изменены.")
        print(f"Будут обработаны файлы в: {args.directory}")
        if args.extensions:
            print(f"Только с расширениями: {args.extensions}")
        
        if unused_patterns:
            print(f"\nПРЕДУПРЕЖДЕНИЕ: {len(unused_patterns)} значений не будут использованы!")
        else:
            print("\nВсе значения из подстановок будут использованы.")
        
        return 0
    
    # Обрабатываем директорию
    print(f"\nОбработка директории: {args.directory}")
    if args.extensions:
        print(f"Только файлы с расширениями: {args.extensions}")
    
    changed, total = process_directory(args.directory, substitutions, args.extensions)
    
    print(f"\nГотово!")
    print(f"Обработано файлов: {total}")
    print(f"Изменено файлов: {changed}")
    
    return 0

if __name__ == "__main__":
    exit(main())