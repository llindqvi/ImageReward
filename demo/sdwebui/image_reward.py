import modules.scripts as scripts
import gradio as gr

from modules import sd_samplers, shared
from modules.processing import (
    Processed,
    process_images,
    StableDiffusionProcessing,
    create_infotext,
)
import modules.images as images
from modules.shared import opts, cmd_opts, state

from modules import script_callbacks
from modules.script_callbacks import ImageSaveParams

import torch
import os
import sys
from pathlib import Path
import ImageReward as reward

def unload_image_reward_model():
    del shared.image_reward_model

scores = {}
using_image_reward = False

class Script(scripts.Script):
    def title(self):
        return "ImageReward - generate human preference scores"

    def show(self, is_txt2img):
        return True

    def ui(self, is_txt2img):
        with gr.Blocks():
            with gr.Row():
                gr.Markdown(
                    value="**Tip**: It will take a little time to **load** the ImageReward model before the first generation."
                )
            with gr.Row():
                with gr.Column():
                    filter_out_low_scores = gr.Checkbox(
                        value=False, label="Filter out images with low scores"
                    )
                with gr.Column():
                    lower_score_limit = gr.Textbox(value=0, label="Lower score limit")
            with gr.Row():
                gr.Markdown(
                    value="ImageReward model takes about **1,600 MB** of memory."
                )
            with gr.Row():
                unload_button = gr.Button(value="Unload Model")
                unload_button.click(unload_image_reward_model)

        return [filter_out_low_scores, lower_score_limit]

    def run(self, p, filter_out_low_scores, lower_score_limit):
        try:
            shared.image_reward_model  # if loaded, do nothing
        except AttributeError:
            # load the model
            # by default, it will:
            # 1. set the device to cuda if available
            # 2. download the model and cache it in `~/.cache/` if model is not found
            # you can alse configure the device and cache dir by passing in the arguments
            shared.image_reward_model = reward.load(
                "ImageReward-v1.0"
            )  # using shared to make the model object global among modules

        # preprocess parameters
        if lower_score_limit != "":
            lower_score_limit = float(lower_score_limit)

        # generate images
        scores.clear()
        global using_image_reward
        using_image_reward = True
        proc = process_images(p)
        using_image_reward = False

        # score
        gens = proc.images
        index = 0
        for img in gens:
            score = None
            if index >= proc.index_of_first_image:
                seed = proc.seed + index - proc.index_of_first_image
                if seed in scores:
                    score = scores[seed]
            if score is not None:
                img.info["score"] = score
                img.info["parameters"] += f", ImageReward Score: {score:.4f}"
            index += 1

        # filter out images with scores lower than the lower limit
        if filter_out_low_scores:
            imgs = list(filter(lambda x: x.info["score"] > lower_score_limit, gens))
        else:
            imgs = gens

        # append score to info
        infotexts = [img.info["parameters"] for img in imgs]

        # sort to score
        img_info_list = list(zip(imgs, infotexts))
        img_info_list.sort(key=lambda x: x[0].info["score"] if "score" in x[0].info else 100000, reverse=True)
        imgs, infotexts = list(zip(*img_info_list))

        # return Processed object
        return Processed(
            p=p,
            images_list=imgs,
            info=proc.info,
            seed=proc.seed,
            infotexts=infotexts,
            index_of_first_image=proc.index_of_first_image,
        )

def on_before_image_saved(params: ImageSaveParams):
    global using_image_reward
    if not using_image_reward:
        return
    with torch.no_grad():
        score = shared.image_reward_model.score(params.p.prompt, params.image)
        seed = int(params.pnginfo["parameters"].split("Seed: ")[1].split(",")[0])
        scores[seed] = score
        params.pnginfo["parameters"] += f", ImageReward Score: {score:.4f}"

    return params


script_callbacks.on_before_image_saved(on_before_image_saved)
