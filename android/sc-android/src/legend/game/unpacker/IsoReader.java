package legend.game.unpacker;

import java.io.FileDescriptor;
import java.io.FileInputStream;
import java.io.IOException;
import java.lang.reflect.Field;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.HashMap;
import java.util.Map;

/**
 * [sc-android] Same API as the retail IsoReader (RandomAccessFile), backed by a FileChannel. On Android the player's
 * discs are files chosen with the system file picker: the app holds them open and links isos/discN.bin ->
 * /proc/self/fd/N, but opening that path again is checked against the file's owner (media_rw) and fails. Such links are
 * read straight from the already open descriptor (same process), through one shared channel per descriptor with
 * positional reads (closing a reader never closes the descriptor).
 */
public class IsoReader {
  public static final int SECTOR_SIZE = 2352;
  public static final int SYNC_PATTER_SIZE = 12;

  private static final Map<Integer, FileChannel> SHARED = new HashMap<>();

  private final Path path;
  private final FileChannel channel;
  private final boolean shared;
  private final long size;
  private long pos;

  public final int lba;

  public IsoReader(final Path path) throws IOException {
    this.path = path;
    final Integer fd = procFd(path);
    if(fd != null) {
      synchronized(SHARED) {
        FileChannel c = SHARED.get(fd);
        if(c == null) {
          c = openFd(fd);
          SHARED.put(fd, c);
        }
        this.channel = c;
      }
      this.shared = true;
    } else {
      this.channel = FileChannel.open(path, StandardOpenOption.READ);
      this.shared = false;
    }
    this.size = this.channel.size();
    this.lba = (int)(this.size / SECTOR_SIZE);
  }

  /** N when path is a symbolic link to /proc/self/fd/N */
  private static Integer procFd(final Path path) {
    try {
      if(Files.isSymbolicLink(path)) {
        final String target = Files.readSymbolicLink(path).toString();
        if(target.startsWith("/proc/self/fd/")) {
          return Integer.parseInt(target.substring("/proc/self/fd/".length()));
        }
      }
    } catch(final IOException | NumberFormatException ignored) {
      // not one of ours
    }
    return null;
  }

  private static FileChannel openFd(final int fd) throws IOException {
    try {
      final FileDescriptor descriptor = new FileDescriptor();
      final Field field = FileDescriptor.class.getDeclaredField("fd");
      field.setAccessible(true); // needs --add-opens java.base/java.io=ALL-UNNAMED (libsclauncher.so)
      field.setInt(descriptor, fd);
      return new FileInputStream(descriptor).getChannel();
    } catch(final ReflectiveOperationException | RuntimeException e) {
      throw new IOException("Cannot use file descriptor " + fd, e);
    }
  }

  public void close() throws IOException {
    if(!this.shared) {
      this.channel.close();
    }
  }

  public long getPos() throws IOException {
    return this.pos;
  }

  public void setPos(final long pos) throws IOException {
    this.pos = pos;
  }

  public void seekSector(final long sector) throws IOException {
    this.pos = sector * SECTOR_SIZE + SYNC_PATTER_SIZE;
  }

  public void seekSectorRaw(final long sector) throws IOException {
    this.pos = sector * SECTOR_SIZE;
  }

  public void advance(final int amount) throws IOException {
    // RandomAccessFile.skipBytes: skips at most to the end of the file, nothing for negative amounts
    final int skipped = amount <= 0 ? 0 : (int)Math.min(amount, Math.max(0, this.size - this.pos));
    this.pos += skipped;

    if(skipped != amount) {
      throw new RuntimeException("Skipped the wrong number of bytes. End of file? Negative amount? (requested: " + amount + ", actual: " + skipped + ')');
    }
  }

  public void read(final byte[] out) throws IOException {
    this.read(out, 0, out.length);
  }

  public void read(final byte[] out, final int offset, final int length) throws IOException {
    // RandomAccessFile.read reads what is available (may be short at the end of the file)
    final ByteBuffer buf = ByteBuffer.wrap(out, offset, length);
    while(buf.hasRemaining()) {
      final int n = this.channel.read(buf, this.pos);
      if(n <= 0) {
        break;
      }
      this.pos += n;
    }
  }

  public byte[] readSectors(int sector, final int length, final boolean raw) {
    int sectorsRead = 0;
    int dataRead = 0;
    boolean endOfRecord = false;
    final int sectorCount = (length + 0x7ff) / 0x800;

    try {
      final byte[] sectorData = new byte[0x930];

      int sectorSize = 0;
      byte[] data = null;

      while(!endOfRecord) {
        this.seekSectorRaw(sector);
        this.read(sectorData);

        if(data == null) {
          sectorSize = raw || ((sectorData[16 + 2] >>> 5) & 1) != 0 ? 0x930 : 0x800; // Form2
          data = new byte[raw ? sectorSize * sectorCount : length];
        }

        endOfRecord = sectorsRead >= sectorCount - 1;

        if(raw) {
          System.arraycopy(sectorData, 0, data, dataRead, sectorSize);
        } else {
          System.arraycopy(sectorData, 24, data, dataRead, Math.min(sectorSize, length - dataRead));
        }

        dataRead += sectorSize;
        sector++;
        sectorsRead++;
      }

      return data;
    } catch(final IOException e) {
      throw new RuntimeException(e);
    }
  }

  @Override
  public String toString() {
    return "ISO Reader " + this.path;
  }
}
