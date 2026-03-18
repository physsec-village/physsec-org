from pydantic import EmailStr, BaseModel
class FormSchema(BaseModel):
    email: EmailStr
    message: str
    name: str
    subject: str