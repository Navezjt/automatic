import os
from modules import shared, devices, files_cache, sd_models


unet_dict = {}
debug = os.environ.get('SD_LOAD_DEBUG', None) is not None


def load_unet(model):
    if shared.opts.sd_unet == 'None':
        return
    if shared.opts.sd_unet not in list(unet_dict):
        shared.log.error(f'UNet model not found: {shared.opts.sd_unet}')
        return
    config_file = os.path.splitext(unet_dict[shared.opts.sd_unet])[0] + '.json'
    if os.path.exists(config_file):
        config = shared.readfile(config_file)
    else:
        config = None
        config_file = 'default'
    try:
        if "StableCascade" in model.__class__.__name__:
            from modules.model_stablecascade import load_prior
            prior_unet, prior_text_encoder = load_prior(unet_dict[shared.opts.sd_unet], config_file=config_file)
            if prior_unet is not None:
                model.prior_pipe.prior = None # Prevent OOM
                model.prior_pipe.prior = prior_unet.to(devices.device, dtype=devices.dtype_unet)
            if prior_text_encoder is not None:
                model.prior_pipe.text_encoder = None # Prevent OOM
                model.prior_pipe.text_encoder = prior_text_encoder.to(devices.device, dtype=devices.dtype)
        if "Flux" in model.__class__.__name__:
            from modules.model_flux import load_transformer
            transformer = load_transformer(unet_dict[shared.opts.sd_unet])
            if transformer is not None:
                model.transformer = None
                if shared.opts.diffusers_offload_mode == 'none':
                    sd_models.move_model(transformer, devices.device)
                model.transformer = transformer
                from modules.sd_models import set_diffuser_offload
                set_diffuser_offload(model, 'model')
        else:
            if not hasattr(model, 'unet') or model.unet is None:
                shared.log.error('UNet not found in current model')
                return
            shared.log.info(f'Loading UNet: name="{shared.opts.sd_unet}" file="{unet_dict[shared.opts.sd_unet]}" config="{config_file}"')
            from diffusers import UNet2DConditionModel
            from safetensors.torch import load_file
            unet = UNet2DConditionModel.from_config(model.unet.config if config is None else config).to(devices.device, devices.dtype)
            state_dict = load_file(unet_dict[shared.opts.sd_unet])
            unet.load_state_dict(state_dict)
            model.unet = unet.to(devices.device, devices.dtype_unet)
    except Exception as e:
        shared.log.error(f'Failed to load UNet model: {e}')
        if debug:
            from modules import errors
            errors.display(e, 'UNet load:')
        return
    devices.torch_gc()


def refresh_unet_list():
    unet_dict.clear()
    for file in files_cache.list_files(shared.opts.unet_dir, ext_filter=[".safetensors"]):
        name = os.path.splitext(os.path.basename(file))[0]
        unet_dict[name] = file
    shared.log.debug(f'Available UNets: path="{shared.opts.unet_dir}" items={len(unet_dict)}')
