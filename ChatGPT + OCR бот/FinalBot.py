# -*- coding: utf-8 -*-
import os
import aiohttp
import easyocr
import urllib.request
import json
import yaml
import ssl
from dotenv import load_dotenv
from openai import OpenAI
import time
from PIL import Image
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
import datetime
from aiogram.dispatcher import FSMContext
from aiogram.contrib.fsm_storage.memory import MemoryStorage
import asyncio


def load_config():
    with open("config.yaml", "r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def increase_image_resolution(image_path, scale_factor=2):
    image = Image.open(image_path)
    new_size = (int(image.width * scale_factor), int(image.height * scale_factor))
    resized_image = image.resize(new_size, Image.ANTIALIAS)
    resized_image_path = image_path.replace(".jpg", "_resized.jpg")
    resized_image.save(resized_image_path)
    return resized_image_path


load_dotenv()
ssl._create_default_https_context = ssl._create_unverified_context

reader = easyocr.Reader(["ru", "en"], gpu=True)
TOKEN = os.getenv("TOKEN")

client = OpenAI(
    api_key=os.getenv("API_KEY"),
    base_url="https://api.proxyapi.ru/openai/v1",
)
model_engine = "gpt-3.5-turbo-0125"

storage = MemoryStorage()
bot = Bot(token=TOKEN)
dp = Dispatcher(bot, storage=storage)
result_storage_path = "temp"
print("Готов к работе")
config = load_config()
system_prompt = config["system_prompt"]

photos_data = []
flag0 = True
counter = 1


@dp.message_handler(content_types=["photo"])
async def photo_handler(message: types.Message, state: FSMContext):

    photos_list0 = []
    photos_list0.append(message.photo[-1])

    await state.update_data(photo_counter=1, photos_list=photos_list0)

    await state.set_state("next_photo")

    await asyncio.sleep(3)

    global flag0
    if flag0:

        async with state.proxy() as data:
            global photos_data
            photos_data = data["photos_list"]
        await request_to_gpt(photos_data, model_engine, system_prompt, client, message)

        photos_data = []

        await state.finish()


@dp.message_handler(content_types=["photo"], state="next_photo")
async def next_photo_handler(message: types.Message, state: FSMContext):

    global flag0
    flag0 = False

    async with state.proxy() as data:
        data["photo_counter"] += 1
        data["photos_list"].append(message.photo[-1])

    await state.set_state("next_photo")

    await asyncio.sleep(2)

    global counter
    if counter == data["photo_counter"] - 1:

        async with state.proxy() as data:
            global photos_data
            photos_data = data["photos_list"]
            # print(data)

        await request_to_gpt(photos_data, model_engine, system_prompt, client, message)

        photos_data = []

        counter = 1
        await state.finish()
        flag0 = True
    else:
        counter += 1


def split_message(message, max_length=4096):
    """
    Разбивает сообщение на части, каждая из которых не превышает max_length символов.
    """
    # Разбиение исходного сообщения на части
    parts = []
    while len(message) > max_length:
        part = message[:max_length]
        last_newline = part.rfind("\n")
        # Пытаемся разбить по последнему переносу строки для сохранения целостности абзацев
        if last_newline != -1:
            parts.append(part[:last_newline])
            message = message[last_newline + 1 :]
        else:
            parts.append(part)
            message = message[max_length:]
    parts.append(message)
    return parts


async def save_images_from_message(photos_data):
    date = f"{datetime.date.today()}"
    images_path = []
    for photo in photos_data:
        # [-1] - получение фото с самым высоким разрешением из массива различных разрешений
        # путь - папка темп в текущей директории
        path = os.path.join("temp", date, photo.file_id + ".jpg")
        await photo.download(destination=path)
        images_path.append(path)

    return images_path


async def request_to_gpt(photos_data, model_engine, system_prompt, client, message):
    images = await save_images_from_message(photos_data)
    all_text = []
    print("ДЛИНА СООБЩЕНИЯ = ", len(images))
    for image_name in images:
        result = reader.readtext(image_name, detail=0)
        all_text.extend(result)
    all_text_str = " ".join(all_text)
    while True:
        try:
            print(1)
            response = client.chat.completions.create(
                model=model_engine,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": all_text_str
                        + " Отвечай строго в формате JSON, должно быть два поля: 'right_answer' и 'expert'. Эксперт тот, кто пишется через знак '@'. Ничего лишнего больше не присылай. Только JSON c двумя ключами: 'right_answer' и 'expert'.",
                    },
                ],
                max_tokens=1024,
                temperature=0.5,
            )
            break
        except:
            print(2)
            time.sleep(10)
    print(3)
    response_content = json.loads(response.choices[0].message.content)
    question = "".join(all_text_str)
    answer = response_content["right_answer"]
    expert = response_content["expert"]

    reply_message = (
        f"ВОПРОС:\n{question}\n\n"
        f"""ОТВЕТ:\nЯ думаю так, но если эксперт ответит по-другому, он прав:\n
{answer}\n\n"""
        f"ЭКСПЕРТ по этому вопросу: {expert}"
    )
    parts = split_message(reply_message)
    for part in parts:
        await message.reply(part)


executor.start_polling(dp, skip_updates=True)
