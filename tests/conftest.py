import pytest
from sqlalchemy.orm import sessionmaker

from app.db import Base, create_db_engine


@pytest.fixture
def factory():
    engine = create_db_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield sessionmaker(engine)
    engine.dispose()
