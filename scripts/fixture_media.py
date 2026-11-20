"""Invented comic metadata and a bounded pool of actual PNG cover/reader images."""

FIRST = ("Mira", "Tavi", "Neri", "Elin", "Sora", "Alba", "Ivo", "Lumi", "Ravi", "Orin")
LAST = ("Vale", "Moss", "Reed", "Finch", "Rowan", "Wren", "Ash", "Lake", "Hale", "Cove")
PLACES = ("Lantern Harbor", "Paper Orchard", "Copper Meadow", "Glass Valley", "Velvet Station",
          "Rainwater Alley", "Cobalt Garden", "Quiet Observatory", "Mossbound Tower", "Apricot Island")
OBJECTS = ("Clockwork Kite", "Moonlit Parcel", "Lost Compass", "Silver Teapot", "Winter Map",
           "Borrowed Umbrella", "Last Postcard", "Sleeping Train", "Tiny Lighthouse", "Hidden Workshop")


def author_name(rng):
    return f"{rng.choice(FIRST)} {rng.choice(LAST)}"


def provider_name(rng, index):
    return f"{rng.choice(PLACES)} Comics {index:03d}"


def works(rng, count):
    result = []
    used = set()
    for index in range(count):
        title = f"The {rng.choice(OBJECTS)} of {rng.choice(PLACES)}"
        while title in used:
            title = f"The {rng.choice(OBJECTS)} of {rng.choice(PLACES)}"
        used.add(title)
        pool = rng.randrange(6)
        result.append({
            "id": f"comic-{index:03d}", "title": title, "author": author_name(rng),
            "description": f"An invented illustrated story about a curious courier and an unexpected discovery. {title} is synthetic fixture content, not a published comic.",
            "cover": f"pages/cover-{pool}.png",
            "tags": ["Synthetic", rng.choice(("Adventure", "Mystery", "Slice of life", "Fantasy"))],
            "chapters": [{"id": f"chapter-{chapter + 1}",
                          "title": f"{chapter + 1}. {rng.choice(('A curious arrival', 'The unopened letter', 'Beyond the bridge', 'A light in the rain', 'The long way home'))}",
                          "pages": [f"pages/story-{pool}-{page}.png" for page in range(4)]}
                         for chapter in range(rng.randint(2, 4))],
        })
    return result


def write_pages(directory, rng):
    # Pillow is used only by explicitly invoked generation, never by serve/index.
    from PIL import Image, ImageDraw, ImageFont

    directory.mkdir(parents=True, exist_ok=True)
    title_font = ImageFont.load_default(size=28)
    font = ImageFont.load_default(size=19)
    conversations = (
        ("The parcel had no address.", "But someone was waiting for it."),
        ("Did you hear that bell?", "The station closed years ago."),
        ("Follow the blue lanterns.", "They always lead somewhere new."),
        ("I think this is your map.", "Then our journey can begin."),
    )
    for pool in range(6):
        color = tuple(rng.randint(55, 175) for _ in range(3))
        cover = Image.new("RGB", (480, 680), (246, 242, 232))
        draw = ImageDraw.Draw(cover)
        draw.rectangle((24, 24, 456, 656), outline=(25, 30, 40), width=5)
        draw.text((48, 52), "SYNTHETIC COMIC", fill=(25, 30, 40), font=title_font)
        draw.rounded_rectangle((48, 132, 432, 570), radius=20, fill=color)
        draw.ellipse((135, 200, 345, 410), fill=(250, 226, 175), outline=(25, 30, 40), width=4)
        draw.polygon(((130, 560), (240, 385), (355, 560)), fill=(35, 45, 65))
        draw.text((48, 602), "Invented stories / demo artwork", fill=(25, 30, 40), font=font)
        cover.save(directory / f"cover-{pool}.png", format="PNG")
        for page, dialogue in enumerate(conversations):
            image = Image.new("RGB", (720, 1040), (250, 247, 239))
            draw = ImageDraw.Draw(image)
            draw.text((32, 20), f"COURIER'S JOURNEY / PAGE {page + 1}", fill=(25, 30, 40), font=title_font)
            for panel in range(2):
                top = 84 + panel * 450
                draw.rectangle((30, top, 690, top + 418), fill=color, outline=(25, 30, 40), width=5)
                for building in range(5):
                    x = 40 + building * 130
                    height = rng.randint(70, 170)
                    draw.rectangle((x, top + 380 - height, x + 108, top + 408), fill=(55, 65, 80))
                    draw.rectangle((x + 24, top + 395 - height, x + 48, top + 420 - height), fill=(250, 216, 130))
                draw.ellipse((260, top + 160, 370, top + 270), fill=(252, 220, 169), outline=(25, 30, 40), width=3)
                draw.polygon(((245, top + 408), (315, top + 270), (390, top + 408)), fill=(37, 49, 69))
                draw.rounded_rectangle((60, top + 25, 660, top + 108), radius=24,
                                       fill=(255, 255, 255), outline=(25, 30, 40), width=3)
                draw.text((82, top + 53), dialogue[panel], fill=(25, 30, 40), font=title_font)
            draw.text((32, 1004), "Synthetic fixture artwork. No external comic assets.", fill=(25, 30, 40), font=font)
            image.save(directory / f"story-{pool}-{page}.png", format="PNG")
