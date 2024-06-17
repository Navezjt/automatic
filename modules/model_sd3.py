import io
import os
import contextlib
import warnings
import torch
import diffusers
import transformers
import rich.traceback


rich.traceback.install()
warnings.filterwarnings(action="ignore", category=FutureWarning)
loggedin = False


def hf_login():
    global loggedin # pylint: disable=global-statement
    import huggingface_hub as hf
    from modules import shared
    if shared.opts.huggingface_token is not None and len(shared.opts.huggingface_token) > 2 and not loggedin:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            hf.login(shared.opts.huggingface_token)
        text = stdout.getvalue() or ''
        line = [l for l in text.split('\n') if 'Token' in l]
        shared.log.info(f'HF login: {line[0] if len(line) > 0 else text}')
        loggedin = True


def load_sd3(te3=None, fn=None, cache_dir=None, config=None):
    from modules import devices
    hf_login()
    repo_id = 'stabilityai/stable-diffusion-3-medium-diffusers'
    model_id = 'stabilityai/stable-diffusion-3-medium-diffusers'
    dtype = torch.float16
    kwargs = {}
    if fn is not None and fn.endswith('.safetensors') and os.path.exists(fn):
        model_id = fn
        loader = diffusers.StableDiffusion3Pipeline.from_single_file
        kwargs = {
            'text_encoder': transformers.CLIPTextModelWithProjection.from_pretrained(
                repo_id,
                subfolder='text_encoder',
                cache_dir=cache_dir,
                torch_dtype=dtype,
            ),
            'text_encoder_2': transformers.CLIPTextModelWithProjection.from_pretrained(
                repo_id,
                subfolder='text_encoder_2',
                cache_dir=cache_dir,
                torch_dtype=dtype,
            ),
            'tokenizer': transformers.CLIPTokenizer.from_pretrained(
                repo_id,
                subfolder='tokenizer',
                cache_dir=cache_dir,
            ),
            'tokenizer_2': transformers.CLIPTokenizer.from_pretrained(
                repo_id,
                subfolder='tokenizer_2',
                cache_dir=cache_dir,
            ),
        }
    else:
        model_id = repo_id
        loader = diffusers.StableDiffusion3Pipeline.from_pretrained
    if te3 == 'fp16':
        text_encoder_3 = transformers.T5EncoderModel.from_pretrained(
            repo_id,
            subfolder='text_encoder_3',
            torch_dtype=dtype,
            cache_dir=cache_dir,
        )
        pipe = loader(
            model_id,
            torch_dtype=dtype,
            text_encoder_3=text_encoder_3,
            cache_dir=cache_dir,
            config=config,
            **kwargs,
        )
    elif te3 == 'fp8':
        quantization_config = transformers.BitsAndBytesConfig(load_in_8bit=True)
        text_encoder_3 = transformers.T5EncoderModel.from_pretrained(
            repo_id,
            subfolder='text_encoder_3',
            quantization_config=quantization_config,
            cache_dir=cache_dir,
            config=config,
        )
        pipe = loader(
            model_id,
            text_encoder_3=text_encoder_3,
            device_map='balanced',
            torch_dtype=dtype,
            cache_dir=cache_dir,
            config=config,
            **kwargs,
        )
    else:
        pipe = loader(
            model_id,
            torch_dtype=dtype,
            text_encoder_3=None,
            cache_dir=cache_dir,
            config=config,
            **kwargs,
        )
    diffusers.pipelines.auto_pipeline.AUTO_TEXT2IMAGE_PIPELINES_MAPPING["stable-diffusion-3"] = diffusers.StableDiffusion3Pipeline
    diffusers.pipelines.auto_pipeline.AUTO_IMAGE2IMAGE_PIPELINES_MAPPING["stable-diffusion-3"] = diffusers.StableDiffusion3Img2ImgPipeline
    devices.torch_gc(force=True)
    return pipe


def load_te3(pipe, te3=None, cache_dir=None):
    from modules import devices
    hf_login()
    repo_id = 'stabilityai/stable-diffusion-3-medium-diffusers'
    if pipe is None or not hasattr(pipe, 'text_encoder_3'):
        return pipe
    if 'fp16' in te3.lower():
        pipe.text_encoder_3 = transformers.T5EncoderModel.from_pretrained(
            repo_id,
            subfolder='text_encoder_3',
            # torch_dtype=dtype,
            cache_dir=cache_dir,
            torch_dtype=pipe.text_encoder.dtype,
        )
    elif 'fp8' in te3.lower():
        from installer import install
        install('bitsandbytes', quiet=True)
        quantization_config = transformers.BitsAndBytesConfig(load_in_8bit=True)
        pipe.text_encoder_3 = transformers.T5EncoderModel.from_pretrained(
            repo_id,
            subfolder='text_encoder_3',
            quantization_config=quantization_config,
            cache_dir=cache_dir,
            torch_dtype=pipe.text_encoder.dtype,
        )
    else:
        pipe.text_encoder_3 = None
    if getattr(pipe, 'text_encoder_3', None) is not None and getattr(pipe, 'tokenizer_3', None) is None:
        pipe.tokenizer_3 = transformers.T5TokenizerFast.from_pretrained(
            repo_id,
            subfolder='tokenizer_3',
            cache_dir=cache_dir,
        )
    devices.torch_gc(force=True)


if __name__ == '__main__':
    model_fn = '/mnt/models/stable-diffusion/sd3/sd3_medium_incl_clips.safetensors'
    import time
    import logging
    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger('sd')
    t0 = time.time()
    pipeline = load_sd3(te3='fp16', fn='')

    # pipeline.to('cuda')
    t1 = time.time()
    log.info(f'Loaded: time={t1-t0:.3f}')

    # pipeline.scheduler = diffusers.schedulers.EulerAncestralDiscreteScheduler.from_config(pipeline.scheduler.config)
    log.info(f'Scheduler, {pipeline.scheduler}')
    image = pipeline(
        prompt='a photo of a cute robot holding a sign above his head that says sdnext, high detailed',
        negative_prompt='',
        num_inference_steps=50,
        height=1024,
        width=1024,
        guidance_scale=7.0,
    ).images[0]
    t2 = time.time()
    log.info(f'Generated: time={t2-t1:.3f}')
    image.save("/tmp/sd3.png")
