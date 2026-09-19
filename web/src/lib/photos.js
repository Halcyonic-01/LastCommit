// Every photograph is chosen to carry the same meaning as the words beside it.
// `lqip` is a ~20px blur inlined as base64 — it paints on the first frame so a
// 2G phone shows the right colour and shape long before the WebP arrives.
// Attribution lives in /public/photos/credits.json and is rendered on the image.
export const PHOTOS = {
  land: {
    src: "/photos/land.webp",
    alt: {"kn": "ಎತ್ತುಗಳಿಂದ ಉಳುಮೆ ಮಾಡಿದ, ಇನ್ನೂ ಬಿತ್ತದ ಹೊಲ", "en": "A field ploughed by bullocks, furrows cut, nothing sown yet"},
    credit: "Ramkumar Radhakrishnan",
    licence: "CC0",
    lqip: "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABQODxIPDRQSEBIXFRQYHjIhHhwcHj0sLiQySUBMS0dARkVQWnNiUFVtVkVGZIhlbXd7gYKBTmCNl4x9lnN+gXz/2wBDARUXFx4aHjshITt8U0ZTfHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHz/wAARCAAOABQDASIAAhEBAxEB/8QAFwABAQEBAAAAAAAAAAAAAAAABAADBf/EAB4QAQACAgIDAQAAAAAAAAAAAAEAAgMRBBITQVFh/8QAFgEBAQEAAAAAAAAAAAAAAAAAAgED/8QAGREBAQADAQAAAAAAAAAAAAAAAQACERIT/9oADAMBAAIRAxEAPwBOXDxaL47V/DcBk4+NV7izl1y2t7Zp2fsyFxm6ZThF2WJQhdTe5RejTgv/2Q==",
  },
  sowing: {
    src: "/photos/sowing.webp",
    alt: {"kn": "ಬುಟ್ಟಿಯಿಂದ ಕೈಯಲ್ಲಿ ಬೀಜ ಬಿತ್ತುತ್ತಿರುವ ರೈತ", "en": "A farmer broadcasting seed by hand from a basket"},
    credit: "Pappu Sarkar01",
    licence: "CC BY-SA 4.0",
    lqip: "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABQODxIPDRQSEBIXFRQYHjIhHhwcHj0sLiQySUBMS0dARkVQWnNiUFVtVkVGZIhlbXd7gYKBTmCNl4x9lnN+gXz/2wBDARUXFx4aHjshITt8U0ZTfHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHz/wAARCAAPABQDASIAAhEBAxEB/8QAGAAAAgMAAAAAAAAAAAAAAAAAAAMBAgT/xAAcEAACAgMBAQAAAAAAAAAAAAABAgADBBESIWH/xAAXAQADAQAAAAAAAAAAAAAAAAAAAgME/8QAGBEAAwEBAAAAAAAAAAAAAAAAAAERAiH/2gAMAwEAAhEDEQA/AL9+fIzGQZGwG0wkKAyEERXdmKrOmpnylSj4MsxlVyC4JhMSm24dk+mEZwIf/9k=",
  },
  rain: {
    src: "/photos/rain.webp",
    alt: {"kn": "ಹಸಿರು ಗದ್ದೆಯ ಮೇಲೆ ಕಪ್ಪು ಮಳೆ ಮೋಡ", "en": "A dark rain cloud moving over green paddy fields"},
    credit: "Sriyaxyzphotos",
    licence: "CC BY-SA 4.0",
    lqip: "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABQODxIPDRQSEBIXFRQYHjIhHhwcHj0sLiQySUBMS0dARkVQWnNiUFVtVkVGZIhlbXd7gYKBTmCNl4x9lnN+gXz/2wBDARUXFx4aHjshITt8U0ZTfHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHz/wAARCAAMABQDASIAAhEBAxEB/8QAGAAAAwEBAAAAAAAAAAAAAAAAAAYHAwX/xAAjEAABAwIFBQAAAAAAAAAAAAACAAEDBBEFEhQxkSEjU3GB/8QAFgEBAQEAAAAAAAAAAAAAAAAAAAED/8QAFREBAQAAAAAAAAAAAAAAAAAAABL/2gAMAwEAAhEDEQA/AONQzHKfcJrJpwumhJmI5Bt7ScLMO3RajLIOxk31Z0KML04jbOPKFO9TN5C5QrY//9k=",
  },
  monsoon: {
    src: "/photos/monsoon.webp",
    alt: {"kn": "ಹಸಿರು ಗುಡ್ಡಗಳ ಮೇಲೆ ದಟ್ಟ ಮುಂಗಾರು ಮೋಡ", "en": "Heavy monsoon cloud over green hills and full water"},
    credit: "Ashwin Arun Yadav",
    licence: "CC BY-SA 4.0",
    lqip: "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABQODxIPDRQSEBIXFRQYHjIhHhwcHj0sLiQySUBMS0dARkVQWnNiUFVtVkVGZIhlbXd7gYKBTmCNl4x9lnN+gXz/2wBDARUXFx4aHjshITt8U0ZTfHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHz/wAARCAALABQDASIAAhEBAxEB/8QAFwAAAwEAAAAAAAAAAAAAAAAAAAQGBf/EAB0QAAIBBQEBAAAAAAAAAAAAAAABAgMFEiExERX/xAAVAQEBAAAAAAAAAAAAAAAAAAAAAv/EABcRAQADAAAAAAAAAAAAAAAAAAABERL/2gAMAwEAAhEDEQA/AFI3BZqLG/pUqcO7JjJ5dYRlL17Y1Kab0rzTyemBOtv3oDUlP//Z",
  },
  ragi: {
    src: "/photos/ragi.webp",
    alt: {"kn": "ಹೊಲದಲ್ಲಿ ನಿಂತ ರಾಗಿ ತೆನೆ", "en": "A ragi earhead standing in the crop"},
    credit: "Kavali Chandrakanth KCK",
    licence: "CC BY-SA 4.0",
    lqip: "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABQODxIPDRQSEBIXFRQYHjIhHhwcHj0sLiQySUBMS0dARkVQWnNiUFVtVkVGZIhlbXd7gYKBTmCNl4x9lnN+gXz/2wBDARUXFx4aHjshITt8U0ZTfHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHz/wAARCAALABQDASIAAhEBAxEB/8QAGAAAAgMAAAAAAAAAAAAAAAAAAAUBAwT/xAAdEAABBAMBAQAAAAAAAAAAAAABAAIDEQUSMSET/8QAFgEBAQEAAAAAAAAAAAAAAAAAAQID/8QAGREBAQADAQAAAAAAAAAAAAAAAQACIkFR/9oADAMBAAIRAxEAPwC0ZeVxoOUDNS3W3EiicdLv21sY0FpJHtLFU7E0GWnIv6ISznEI29qMFv/Z",
  },
  dry: {
    src: "/photos/dry.webp",
    alt: {"kn": "ಹಸಿರು ಹುಲ್ಲಿನ ನಡುವೆ ಬಿರುಕು ಬಿಟ್ಟ ಒಣ ನೆಲ", "en": "Cracked dry earth splitting a green field"},
    credit: "Timo Newton-Syms from Helsinki, Finland & Maid",
    licence: "CC BY-SA 2.0",
    lqip: "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABQODxIPDRQSEBIXFRQYHjIhHhwcHj0sLiQySUBMS0dARkVQWnNiUFVtVkVGZIhlbXd7gYKBTmCNl4x9lnN+gXz/2wBDARUXFx4aHjshITt8U0ZTfHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHz/wAARCAAPABQDASIAAhEBAxEB/8QAFwAAAwEAAAAAAAAAAAAAAAAAAAMEAf/EAB4QAQACAQQDAAAAAAAAAAAAAAEAAgMEERIxIUFh/8QAFQEBAQAAAAAAAAAAAAAAAAAAAgP/xAAaEQACAgMAAAAAAAAAAAAAAAAAAgEREiEi/9oADAMBAAIRAxEAPwDMa2zC+QlGoeVF9kTphrTdje6v2SWNBVeSauVa9MIm5wsnJhDiRqT/2Q==",
  },
  drought: {
    src: "/photos/drought.webp",
    alt: {"kn": "ಬಿರುಕು ಬಿಟ್ಟ ನೆಲದ ಮೇಲೆ ರೈತನ ಕೈ — ಕರ್ನಾಟಕ ಬರ", "en": "A farmer's hand over cracked Karnataka earth during drought"},
    credit: "Pushkarv",
    licence: "CC BY-SA 3.0",
    lqip: "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABQODxIPDRQSEBIXFRQYHjIhHhwcHj0sLiQySUBMS0dARkVQWnNiUFVtVkVGZIhlbXd7gYKBTmCNl4x9lnN+gXz/2wBDARUXFx4aHjshITt8U0ZTfHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHz/wAARCAANABQDASIAAhEBAxEB/8QAGAAAAgMAAAAAAAAAAAAAAAAAAAQCAwX/xAAZEAEAAwEBAAAAAAAAAAAAAAABAAIRA0H/xAAUAQEAAAAAAAAAAAAAAAAAAAAA/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAwDAQACEQMRAD8AV5dIyXGuMz+dnck7WTEfYD5YDCEo2ED/2Q==",
  },
};

export const photo = (name) => PHOTOS[name] ?? PHOTOS.land;
