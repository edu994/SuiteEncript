import io

from PIL import Image

DELIMITER = "@@END_STEGO@@"

def hide_text_in_image(image_bytes: bytes, secret_text: str) -> bytes:
    """Oculta un mensaje de texto dentro de los bits LSB de una imagen PNG."""
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    
    # Preparar el mensaje con un delimitador para saber dónde termina al extraer
    full_message = secret_text + DELIMITER
    binary_message = ''.join(format(ord(char), '08b') for char in full_message)
    
    pixels = list(image.getdata())
    max_capacity_bits = len(pixels) * 3
    
    if len(binary_message) > max_capacity_bits:
        raise ValueError("El mensaje es demasiado largo para la capacidad de esta imagen.")

    new_pixels = []
    bit_idx = 0
    message_len = len(binary_message)

    for pixel in pixels:
        r, g, b = pixel
        if bit_idx < message_len:
            r = (r & ~1) | int(binary_message[bit_idx])
            bit_idx += 1
        if bit_idx < message_len:
            g = (g & ~1) | int(binary_message[bit_idx])
            bit_idx += 1
        if bit_idx < message_len:
            b = (b & ~1) | int(binary_message[bit_idx])
            bit_idx += 1
        new_pixels.append((r, g, b))

    encoded_image = Image.new(image.mode, image.size)
    encoded_image.putdata(new_pixels)

    output_buffer = io.BytesIO()
    encoded_image.save(output_buffer, format="PNG")
    return output_buffer.getvalue()


def extract_text_from_image(image_bytes: bytes) -> str:
    """Extrae un mensaje oculto en los bits LSB de una imagen PNG."""
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    pixels = list(image.getdata())

    extracted_bits = []
    for pixel in pixels:
        for color_channel in pixel[:3]:
            extracted_bits.append(str(color_channel & 1))

    # Convertir grupos de 8 bits a caracteres
    extracted_chars = []
    for i in range(0, len(extracted_bits), 8):
        byte = ''.join(extracted_bits[i:i+8])
        if len(byte) < 8:
            break
        char = chr(int(byte, 2))
        extracted_chars.append(char)
        
        # Verificar si alcanzamos el delimitador de cierre
        current_text = "".join(extracted_chars)
        if DELIMITER in current_text:
            return current_text.replace(DELIMITER, "")

    raise ValueError("No se encontró ningún mensaje oculto o el formato de la imagen no es válido.")