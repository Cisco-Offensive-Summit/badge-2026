import os, asyncio, supervisor, time
from displayio import Group, TileGrid, Bitmap, Palette
import terminalio
from adafruit_display_text.label import Label
import adafruit_imageload
from badge.fileops import is_file
from badge.screens import LCD, EPD, round_button, center_text_x_plane, wrap_message, clear_screen, epd_print_exception
from badge.neopixels import set_neopixels, neopixels_off
import badge.buttons
from badge.events import on
import badge.events as evt
from badge.constants import BB_HEIGHT, BB_WIDTH
from badge.log import log

IMG_DIR = '/img'

class Exit(Exception):
    def __init__(self, message):
        self.message = message          
        super().__init__(message)
    def __str__(self):
        return self.message

#--- indicators when button press
@on(evt.BTN_C_PRESSED)
def on_c_pressed(e):
    set_neopixels(0xFF0000, 0xFF0000, 0xFF0000, 0xFF0000)

@on(evt.BTN_C_RELEASED)
def on_c_released(e):
    neopixels_off()

@on(evt.BTN_D_PRESSED)
def on_d_pressed(e):
    set_neopixels(0x00FF00, 0x00FF00, 0x00FF00, 0x00FF00)

@on(evt.BTN_D_RELEASED)
def on_d_released(e):
    neopixels_off()

def get_img_list():
    img_list = []

    for inode in os.listdir(IMG_DIR):
        file_path = f"{IMG_DIR}/{inode}"
        if is_file(file_path):
            split = file_path.rsplit('.', 1)
            if len(split) < 2:
                continue
            if split[1] == "bmp":
                img_list.append(f"{inode}")

    return img_list

def epd_welcome():
    clear_screen(EPD)
    root = Group()

    text_group = Group()
    text_group.append(center_text_x_plane(EPD, "PrintBMP", y=24, scale=3))
    text_group.append(center_text_x_plane(EPD, "Select a bmp from the '/img'", y=62))
    text_group.append(center_text_x_plane(EPD, "directory to display.", y=74))
    text_group.append(center_text_x_plane(EPD, "bmp dimensions: 264x176x1", y=96))

    buttons_group = Group()
    radius = 5
    margin = 8
    labels = [Label(font=terminalio.FONT, text=t)
              for t in ("  UP  ", " Down ", " Exit ", "Select")]

    def get_button_y(lbl):
        return EPD.height - radius - (lbl.bounding_box[BB_HEIGHT]//2) - margin

    # Spread the buttons evenly across the full width of the panel instead of
    # using the hard-coded offsets the old fixed-size layouts relied on.
    widest = max(lbl.bounding_box[BB_WIDTH] for lbl in labels) + (radius * 2)
    step = ((EPD.width - (margin * 2)) - widest) // (len(labels) - 1)
    for i, lbl in enumerate(labels):
        buttons_group.append(
            round_button(lbl, margin + radius + (i * step), get_button_y(lbl), radius))

    root.append(text_group)
    root.append(buttons_group)

    EPD.root_group = root
    EPD.refresh()


def draw_bmp(file_name: str):
    clear_screen(EPD)
    root = Group()
    try:
        bmp, shader = adafruit_imageload.load(f"{IMG_DIR}/{file_name}",
                                              bitmap=Bitmap, palette=Palette)
    except Exception as e:
        # A corrupt or unsupported bmp should not take the whole app down.
        log(f"could not load {file_name}: {e}")
        root.append(wrap_message(EPD, f"Could not display\n{file_name}\n\n{e}"))
        EPD.root_group = root
        EPD.refresh()
        return

    # Invert only true 1-bit black/white images. A larger palette would get two
    # of its entries clobbered, and non-indexed (16/24-bit) images come back as
    # a ColorConverter, which raises TypeError on item assignment.
    if isinstance(shader, Palette) and len(shader) == 2:
        shader[0] = 0xFFFFFF
        shader[1] = 0x000000

    root.append(TileGrid(bmp, pixel_shader=shader))
    EPD.root_group = root
    EPD.refresh()


def no_images_screen():
    """Shown when /img holds no bitmaps, so the user is not stuck on a dead list."""
    clear_screen(LCD)
    group = Group()
    group.append(center_text_x_plane(LCD, "No bitmaps", y=40))
    group.append(center_text_x_plane(LCD, "found in", y=56))
    group.append(center_text_x_plane(LCD, IMG_DIR, y=72))
    group.append(center_text_x_plane(LCD, "Press Exit", y=96))
    LCD.root_group = group
    

def lcd_welcome(bmp_list: list):
    text_areas = []
    group = Group()
    for i, f in enumerate(bmp_list):
        l = Label(terminalio.FONT)
        l.anchor_point = (0,0)
        l.anchored_position = (1,i*16)
        l.text = f
        group.append(l)
        text_areas.append(l)
    
    return group, text_areas

def set_selection(bmp_list: list, index: int):
    for i in bmp_list:
        i.background_color = 0x000000
        i.color = 0xFFFFFF
    
    bmp_list[index].background_color = 0xaaaaaa
    bmp_list[index].color = 0x111111

def scroll(bmp_list: list, up: bool):
    if up:
        for i in bmp_list:
            i.y -= 16
    else:
        for i in bmp_list:
            i.y += 16


async def main_loop():
    exit_app = False
    while not exit_app:
        epd_welcome()
        img_list = get_img_list()

        # Nothing to show: say so and wait for Exit rather than indexing an
        # empty list (which used to raise IndexError before any input).
        if not img_list:
            no_images_screen()
            while True:
                e = await badge.buttons.any_button_downup()
                if e == evt.BTN_C_DOWNUP:
                    break
            break

        group, bmp_list = lcd_welcome(img_list)
        LCD.root_group = group
        set_selection(bmp_list, 0)

        loc_acc = 0
        file_acc = 0
        while True:
            e = await badge.buttons.any_button_downup()
            if e == evt.BTN_A_DOWNUP:
                if loc_acc == 0 and file_acc > 0:
                    scroll(bmp_list, False)
                loc_acc = 0 if loc_acc == 0 else loc_acc - 1
                file_acc = 0 if file_acc == 0 else file_acc - 1
                set_selection(bmp_list, file_acc)
            elif e == evt.BTN_B_DOWNUP:
                if loc_acc == 7 and file_acc < len(bmp_list) -1:
                    scroll(bmp_list, True)
                loc_acc = 7 if loc_acc == 7 else loc_acc + 1
                file_acc = len(bmp_list) - 1 if file_acc == len(bmp_list) - 1 else file_acc + 1
                set_selection(bmp_list, file_acc)
            elif e == evt.BTN_C_DOWNUP:
                exit_app = True
                break
            elif e == evt.BTN_D_DOWNUP:
                draw_bmp(bmp_list[file_acc].text)
            else:
                log("Unknown Button")
    
    raise Exit("Goodbye!")


async def main():
    neopixels_off()
    button_tasks = badge.buttons.all_tasks(interval=0.1)
    evt_tasks = evt.start_tasks()
    mainloop_task = asyncio.create_task(main_loop())
    all_tasks = [ mainloop_task ] + button_tasks + evt_tasks
    await asyncio.gather(*all_tasks)

supervisor.runtime.autoreload = False
try:
    asyncio.run(main())
except Exit as e:
    log(f"{e}")
except Exception as e:
    epd_print_exception(e)
    time.sleep(60)

supervisor.reload()